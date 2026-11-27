// SPDX-License-Identifier: GPL-2.0-only
/* Experimental RTD1395 SD host, derived from the GPL Realtek BSP protocol.
 * Depends on the tested U-Boot initialization: no power/voltage changes,
 * no hotplug, no UHS. Separate CID/range-bound four-bit, 64 KiB CMD25 candidate.
 * Native CMD18 reads defer copying until checked stream completion; no UHS.
 * All requests use bounded worker polling.
 */
#include <linux/atomic.h>
#include <linux/delay.h>
#include <linux/crc32.h>
#include <linux/dma-mapping.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/mmc/host.h>
#include <linux/mmc/card.h>
#include "write-policy.h"
#include <linux/mmc/mmc.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/scatterlist.h>
#include <linux/slab.h>
#include <linux/unaligned.h>
#include <linux/workqueue.h>

/* Profiling is enabled in the isolated native-write build. */
enum sd_metric {
	SD_REQUESTS, SD_REQUEST_BYTES, SD_REQUEST_ERRORS, SD_REQUEST_NS,
	SD_QUEUE_NS, SD_READ_COMMANDS, SD_READ_COMMAND_NS, SD_SETUP_NS,
	SD_TRANSFER_NS, SD_DMA_NS, SD_COPY_NS, SD_ALLOC_NS,
	SD_TRANSFER_POLLS, SD_STREAM_COMMANDS, SD_WRITE_COMMANDS,
	SD_WRITE_STREAM_COMMANDS, SD_WRITE_COMMAND_NS, SD_PROGRAM_POLLS, SD_METRICS,
};
#ifdef BPI_M4_SD_PROFILE
static bool profile = true;
static unsigned int poll_us = 100;
module_param(profile, bool, 0644);
MODULE_PARM_DESC(profile, "Collect cumulative SD timing counters; change only between samples");
static int sd_set_poll_us(const char *value, const struct kernel_param *kp)
{
	return param_set_uint_minmax(value, kp, 1, 1000);
}
static const struct kernel_param_ops sd_poll_ops = {
	.set = sd_set_poll_us, .get = param_get_uint,
};
module_param_cb(poll_us, &sd_poll_ops, &poll_us, 0644);
MODULE_PARM_DESC(poll_us, "Maximum polling sleep in microseconds (1..1000); default 100");
#endif

/* Immutable native-read gate; default sector-by-sector CMD17. */
static bool native_read;
static char *read_cid;
static unsigned long long read_capacity;
module_param(native_read, bool, 0444);
module_param(read_cid, charp, 0444);
module_param(read_capacity, ullong, 0444);
MODULE_PARM_DESC(native_read, "Enable checked native CMD18 reads; default off");
MODULE_PARM_DESC(read_cid, "Exact lowercase SDHC CID required for native reads");
MODULE_PARM_DESC(read_capacity, "Exact SDHC capacity in sectors for native reads");

#define SD_BUFFER_BYTES (64 * 1024)

#define DMA1 0x004
#define DMA2 0x008
#define DMA3 0x00c
#define SYNC 0x020
#define ISR 0x024
#define ISREN 0x028
#define CKGEN 0x078
#define STOP 0x103
#define CARD_OE 0x104
#define CARD_SELECT 0x10e
#define CARD_CLOCK 0x129
#define EXIST 0x11f
#define CFG1 0x180
#define CFG2 0x181
#define CFG3 0x182
#define ST1 0x183
#define ST2 0x184
#define CMD0 0x189
#define BYTELO 0x18f
#define BYTEHI 0x190
#define BLOCKLO 0x191
#define BLOCKHI 0x192
#define TRANS 0x193

struct sd_probe {
	struct mmc_host *mmc;
	void __iomem *regs;
	void __iomem *bridge;
	void *buffer;
	dma_addr_t dma;
	struct work_struct work;
	struct mmc_request *mrq;
	u32 data_clock;
	u8 bus_bits;
	bool failed;
#ifdef BPI_M4_SD_PROFILE
	atomic64_t stats[SD_METRICS];
	u64 queued_ns;
#endif
};
static struct platform_device *probe_device;

/* Immutable after load: never widen access from a running root filesystem. */
static bool native_write;
module_param(native_write, bool, 0444);
MODULE_PARM_DESC(native_write, "Enable native CMD25 bursts inside the write gate; default CMD24 fallback");
static bool write_enable;
static unsigned long long scratch_start, scratch_sectors;
static char *scratch_cid;
module_param(write_enable, bool, 0444);
module_param(scratch_start, ullong, 0444);
module_param(scratch_sectors, ullong, 0444);
module_param(scratch_cid, charp, 0444);
MODULE_PARM_DESC(write_enable, "Allow CMD24/CMD25 only in the CID-bound scratch range; default false");
MODULE_PARM_DESC(scratch_start, "First explicitly provisioned scratch sector (512-byte units)");
MODULE_PARM_DESC(scratch_sectors, "Size of explicitly provisioned scratch range in sectors");
MODULE_PARM_DESC(scratch_cid, "Exact lowercase 32-digit SDHC CID required for writes");

static bool sd_write_permitted(struct sd_probe *host, u32 sector, u32 blocks)
{
	struct mmc_card *card = host->mmc->card;
	char cid[33];

	if (!write_enable || !card || !mmc_card_is_blockaddr(card) ||
	    !scratch_cid || !sd_write_in_range(scratch_start, scratch_sectors, sector, blocks) ||
	    sector >= card->csd.capacity || blocks > card->csd.capacity - sector)
		return false;
	snprintf(cid, sizeof(cid), "%08x%08x%08x%08x", card->raw_cid[0],
		 card->raw_cid[1], card->raw_cid[2], card->raw_cid[3]);
	return !strcmp(cid, scratch_cid);
}

static bool sd_read_permitted(struct sd_probe *host, u32 sector, u32 blocks)
{
	struct mmc_card *card = host->mmc->card;
	char cid[33];

	if (!native_read || !card || !mmc_card_is_blockaddr(card) || !read_cid ||
	    !read_capacity || read_capacity != card->csd.capacity || !blocks ||
	    blocks > SD_BUFFER_BYTES / 512 || sector >= card->csd.capacity ||
	    blocks > card->csd.capacity - sector)
		return false;
	snprintf(cid, sizeof(cid), "%08x%08x%08x%08x", card->raw_cid[0],
		 card->raw_cid[1], card->raw_cid[2], card->raw_cid[3]);
	return !strcmp(cid, read_cid);
}

static void sd_abort(struct sd_probe *host);

static void sd_freeze(struct sd_probe *host)
{
	sd_abort(host);
	if (!host->failed) {
		host->failed = true;
		__module_get(THIS_MODULE);
		dev_err(mmc_dev(host->mmc), "Uncertain transfer: host frozen; physical reset required\n");
	}
}

static inline u64 sd_now(void)
{
#ifdef BPI_M4_SD_PROFILE
	if (READ_ONCE(profile))
		return ktime_get_ns();
#endif
	return 0;
}
static inline void sd_count(struct sd_probe *host, enum sd_metric metric, u64 value)
{
#ifdef BPI_M4_SD_PROFILE
	if (READ_ONCE(profile))
		atomic64_add(value, &host->stats[metric]);
#endif
}
static inline void sd_elapsed(struct sd_probe *host, enum sd_metric metric, u64 start)
{
	if (start)
		sd_count(host, metric, ktime_get_ns() - start);
}
static inline unsigned int sd_poll_us(void)
{
#ifdef BPI_M4_SD_PROFILE
	return READ_ONCE(poll_us);
#else
	return 100;
#endif
}

#ifdef BPI_M4_SD_PROFILE
static ssize_t read_stats_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	static const char * const names[SD_METRICS] = {
		"requests", "request_bytes", "request_errors", "request_ns",
		"queue_ns", "read_commands", "read_command_ns", "setup_ns",
		"transfer_ns", "dma_ns", "copy_ns", "alloc_ns", "transfer_polls", "stream_commands",
		"write_commands", "write_stream_commands", "write_command_ns", "program_polls",
	};
	struct sd_probe *host = dev_get_drvdata(dev);
	ssize_t length = sysfs_emit(buf,
		"profile=%u\npoll_us=%u\nnative_write=%u\nnative_read=%u\nbus_width=%u\nmax_burst_bytes=%u\n",
		READ_ONCE(profile), READ_ONCE(poll_us), native_write, native_read,
		host->bus_bits ? 4 : 1, SD_BUFFER_BYTES);
	unsigned int i;
#ifdef BPI_M4_SD_MULTIBLOCK
	length += sysfs_emit_at(buf, length, "multi_block=%u\n", READ_ONCE(multi_block));
#endif
	/* Cumulative counters: compare snapshots taken between completed samples. */
	for (i = 0; i < SD_METRICS; i++)
		length += sysfs_emit_at(buf, length, "%s=%llu\n", names[i],
				       (unsigned long long)atomic64_read(&host->stats[i]));
	return length;
}
static DEVICE_ATTR_RO(read_stats);
static struct attribute *sd_profile_attrs[] = { &dev_attr_read_stats.attr, NULL };
static const struct attribute_group sd_profile_group = { .attrs = sd_profile_attrs };
#endif

/* Vendor asm/io.h sync(): drain posted RBUS transactions, not only CPU stores. */
static void sd_sync(struct sd_probe *host)
{
	mb();
	writel(0, host->bridge);
	mb();
}
static u8 sd_transfer_state(struct sd_probe *host)
{
	sd_count(host, SD_TRANSFER_POLLS, 1);
	sd_sync(host);
	return readb(host->regs + TRANS);
}

static void sd_abort(struct sd_probe *host)
{
	u32 value;
	writeb(0xff, host->regs + STOP);
	writel(0, host->regs + DMA3);
	value = readl(host->regs + SYNC);
	writel(value & ~1, host->regs + SYNC);
	writel(value | 1, host->regs + SYNC);
	readl(host->regs + SYNC);
	sd_sync(host);
}

static bool allowed_command(unsigned int opcode)
{
	switch (opcode) {
	case 0: case 2: case 3: case 6: case 7: case 8: case 9: case 10:
	case 12: case 13: case 16: case 17: case 24: case 41: case 51: case 55:
		return true;
	case 18:
		return native_read;
	case MMC_WRITE_MULTIPLE_BLOCK:
		return native_write;
	default:
		return false;
	}
}

static int sd_command(struct sd_probe *host, struct mmc_command *cmd);
static int sd_wait_programmed(struct sd_probe *host, u32 *response)
{
	unsigned long deadline = jiffies + msecs_to_jiffies(3000);
	struct mmc_card *card = host->mmc->card;

	if (!card)
		return -ENODEV;
	do {
		struct mmc_command status = {
			.opcode = MMC_SEND_STATUS, .arg = card->rca << 16,
			.flags = MMC_RSP_R1 | MMC_CMD_AC,
		};
		int ret;
		sd_count(host, SD_PROGRAM_POLLS, 1);
		ret = sd_command(host, &status);

		if (ret)
			return ret;
		if (sd_write_status_error(status.resp[0])) {
			dev_err(mmc_dev(host->mmc), "CMD13 programming error: r1=%08x\n", status.resp[0]);
			return -EIO;
		}
		if (sd_write_status_ready(status.resp[0])) {
			if (response)
				*response = status.resp[0];
			return 0;
		}
		usleep_range(1000, 2000);
	} while (time_before(jiffies, deadline));
	return -ETIMEDOUT;
}
static int sd_command_inner(struct sd_probe *host, struct mmc_command *cmd)
{
	struct mmc_data *data = cmd->data;
	bool long_rsp = cmd->flags & MMC_RSP_136;
	bool writing = data && (data->flags & MMC_DATA_WRITE);
	bool stream_write = cmd->opcode == MMC_WRITE_MULTIPLE_BLOCK;
	bool short_data = data && data->blksz <= 64;
	u8 cfg2, cfg3 = 5, transfer = 8, status;
	u32 dma_status, words[4];
	unsigned int bytes = data ? data->blksz * data->blocks : 0;
	u64 stage_ns = sd_now();
	unsigned int interval = sd_poll_us();
	int ret, i;

	if (host->failed)
		return -EIO;
	if (!allowed_command(cmd->opcode))
		return -EROFS;
	if ((cmd->opcode == MMC_WRITE_BLOCK || stream_write) &&
	    (!writing || !data || !sd_write_permitted(host, cmd->arg, data->blocks)))
		return -EROFS;
	if (writing && ((cmd->opcode != MMC_WRITE_BLOCK && !stream_write) ||
	    data->flags != MMC_DATA_WRITE || data->blksz != 512 ||
	    !data->blocks || data->blocks > SD_BUFFER_BYTES / 512 ||
	    (!stream_write && data->blocks != 1)))
		return -EINVAL;
	if (data)
		data->bytes_xfered = 0;
	if (cmd->opcode == 18 && (!data || !(data->flags & MMC_DATA_READ) ||
	    data->blocks > SD_BUFFER_BYTES / 512))
		return -EINVAL;
	if (data && (!bytes || bytes > (cmd->opcode == 18 || stream_write ? SD_BUFFER_BYTES : 512) ||
	    (data->blocks != 1 && cmd->opcode != 18 && !stream_write) ||
	    (cmd->opcode == 18 && data->blksz != 512)))
		return -EINVAL;
	if (cmd->opcode == 18 && !sd_read_permitted(host, cmd->arg, data->blocks))
		return -EACCES;
	/* Clear only bytes the next DMA will use; status commands use no DMA. */
	if (long_rsp || data)
		memset(host->buffer, 0, long_rsp ? 512 : short_data ? 64 : bytes);
	memset(cmd->resp, 0, sizeof(cmd->resp));
	if (writing && sg_copy_to_buffer(data->sg, data->sg_len, host->buffer, bytes) != bytes)
		return -EIO;
	if (!(cmd->flags & MMC_RSP_PRESENT))
		cfg2 = 0x74;
	else if (long_rsp)
		cfg2 = 0x42;
	else
		cfg2 = data ? 0x01 : 0x41;
	if (!(cmd->flags & MMC_RSP_CRC))
		cfg2 |= 4;
	if (cmd->flags & MMC_RSP_BUSY)
		cfg2 |= 8;
	if (cmd->opcode == 0 || cmd->opcode == 8) {
		writeb(0xd0, host->regs + CFG1);
		cfg3 = 0;
	}
	if (cmd->opcode == 41)
		cfg3 = 0;
	if (cmd->opcode == 12) {
		cfg2 = 0x7c;
		cfg3 = 0;
	}
	if (cmd->opcode == 51)
		cfg2 = 0x41;
	/* BSP non-data CMD13 leaves configure3 unchanged. In particular, do
	 * not enable response checking (0x05) after a stream/stop configured 0.
	 */
	if (cmd->opcode == MMC_SEND_STATUS && !data)
		cfg3 = readb(host->regs + CFG3);
	/* BSP SD CMD18: AUTOREAD1, R1/CRC16 enabled, configure3=0. */
	if (cmd->opcode == 18 || stream_write)
		cfg3 = 0;
	if (data) {
		/* The preceding R2 transfers use the same controller FIFO. */
		writeb(readb(host->regs + CFG1) & ~0x10, host->regs + CFG1);
		/* Use the clock selected by the MMC core after card negotiation. */
		writel(host->data_clock, host->regs + CKGEN);
		writeb(0x10 | host->bus_bits, host->regs + CFG1);
		transfer = stream_write ? 0x09 : writing ? 0x0a : cmd->opcode == 18 ? 0x0d : cmd->opcode == 17 ? 0x0e : 0x0c;
	}
	writeb(0, host->regs + STOP);
	/* Match BSP event enables; GIC IRQ 44 remains masked, worker polls. */
	writel(0x17, host->regs + ISREN);
	writel(0x17, host->regs + ISR);
	writeb(cfg2, host->regs + CFG2);
	writeb(cfg3, host->regs + CFG3);
	writeb(0x40 | cmd->opcode, host->regs + CMD0);
	for (i = 0; i < 4; i++)
		writeb(cmd->arg >> (24 - 8 * i), host->regs + CMD0 + 1 + i);
	writeb(0, host->regs + CMD0 + 5);
	if (long_rsp || data) {
		unsigned int count = short_data ? 64 : 512;
		unsigned int blocks = data ? data->blocks : 1;
		writeb(count, host->regs + BYTELO);
		writeb(count >> 8, host->regs + BYTEHI);
		writeb(blocks, host->regs + BLOCKLO);
		writeb(blocks >> 8, host->regs + BLOCKHI);
		writel(host->dma >> 3, host->regs + DMA1);
		writel(blocks, host->regs + DMA2);
		dma_wmb();
		writel((writing ? 1 : 3) | (long_rsp ? 0x10 : short_data ? 0x20 : 0), host->regs + DMA3);
	}
	sd_sync(host);
	writeb(0x80 | transfer, host->regs + TRANS);
	sd_elapsed(host, SD_SETUP_NS, stage_ns);
	stage_ns = sd_now();
	ret = read_poll_timeout(sd_transfer_state, status,
		(status & 0x60) == 0x60 || (status & 0x10) ||
		(readb(host->regs + ST2) & 1), interval, writing ? 3000000 : 1000000, false, host);
	sd_elapsed(host, SD_TRANSFER_NS, stage_ns);
	if (ret || (status & 0x10) || (readb(host->regs + ST2) & 1)) {
		dev_err(mmc_dev(host->mmc), "CMD%u failed: trans=%02x st1=%02x st2=%02x\n",
			cmd->opcode, status, readb(host->regs + ST1), readb(host->regs + ST2));
		dev_err(mmc_dev(host->mmc), "DMA=%08x/%08x/%08x sync=%08x cfg=%02x/%02x/%02x cmdstate=%02x datastate=%02x bus=%02x\n",
			readl(host->regs + DMA1), readl(host->regs + DMA2), readl(host->regs + DMA3),
			readl(host->regs + SYNC), readb(host->regs + CFG1), readb(host->regs + CFG2),
			readb(host->regs + CFG3), readb(host->regs + 0x195), readb(host->regs + 0x196), readb(host->regs + 0x185));
		/* Abort cannot prove that the controller released DMA ownership. */
		sd_freeze(host);
		return ret ? ret : -EILSEQ;
	}
	if (long_rsp || data) {
		stage_ns = sd_now();
		ret = readl_poll_timeout(host->regs + DMA3, dma_status,
			!(dma_status & 1), interval, 100000);
		sd_elapsed(host, SD_DMA_NS, stage_ns);
		if (ret) {
			sd_freeze(host);
			dev_err(mmc_dev(host->mmc), "DMA timeout: probe frozen; physical reset required\n");
			return ret;
		}
		dma_rmb();
	}
	if (long_rsp) {
		for (i = 0; i < 4; i++)
			words[i] = get_unaligned_be32(host->buffer + 4 * i);
		for (i = 0; i < 3; i++)
			cmd->resp[i] = words[i] << 8 | words[i + 1] >> 24;
		cmd->resp[3] = words[3] << 8 | readb(host->regs + CMD0 + 5);
	} else if ((cmd->flags & MMC_RSP_PRESENT) && (cfg2 & 3) == 1 &&
		   cmd->opcode != 18 && !stream_write) {
		/* The BSP skips CPU response extraction for AUTO_READ1/WRITE1. */
		/* CMD12 configure2=0x7c has response length zero in the BSP.
		 * Its command bytes are not R1; CMD13 checks status after stop.
		 */
		for (i = 0; i < 4; i++)
			cmd->resp[0] = cmd->resp[0] << 8 | readb(host->regs + CMD0 + 1 + i);
	}
	if (cmd->opcode == MMC_SEND_STATUS &&
	    ((readb(host->regs + ST1) & 0x82) || (readb(host->regs + ST2) & 3))) {
		sd_freeze(host);
		cmd->retries = 0;
		return -EILSEQ;
	}
	if (writing) {
		/* AUTOWRITE1 does not expose the initial R1 in CMD registers.
		 * Capture CRC/write errors before CMD12 overwrites controller status.
		 * DMA must be released before stop or any buffer reuse is attempted.
		 */
		if ((readb(host->regs + ST1) & 0xe2) ||
		    (!stream_write && sd_write_status_error(cmd->resp[0])))
			ret = -EILSEQ;
		else if (!stream_write)
			ret = sd_wait_programmed(host, NULL);
		if (ret) {
			dev_err(mmc_dev(host->mmc), "CMD%u write status failed: st1=%02x r1=%08x error=%d\n",
				cmd->opcode, readb(host->regs + ST1), cmd->resp[0], ret);
			sd_freeze(host);
			cmd->retries = 0;
			return ret;
		}
		/* CMD25 bytes remain unacknowledged until CMD12 + READY/TRAN. */
		if (!stream_write)
			data->bytes_xfered = bytes;
	}
	if (cmd->opcode == 7 && cmd->arg && !data) {
		/* Start selection in one-bit mode; the core negotiates four-bit mode
		 * after SCR. Reset host width too before the baseline sector read. */
		struct mmc_command app = { .opcode = 55, .arg = cmd->arg, .flags = MMC_RSP_R1 | MMC_CMD_AC };
		struct mmc_command width = { .opcode = 6, .arg = 0, .flags = MMC_RSP_R1 | MMC_CMD_AC };
		ret = sd_command(host, &app);
		if (!ret)
			ret = sd_command(host, &width);
		if (ret)
			return ret;
		host->bus_bits = 0;
		writeb(readb(host->regs + CFG1) & ~3, host->regs + CFG1);
		{
			u8 *sector = kmalloc(512, GFP_KERNEL);
			struct scatterlist sg;
			struct mmc_data block = { .blksz = 512, .blocks = 1, .flags = MMC_DATA_READ, .sg = &sg, .sg_len = 1 };
			struct mmc_command read = { .opcode = 17, .arg = 0, .flags = MMC_RSP_R1 | MMC_CMD_ADTC, .data = &block };
			if (!sector)
				return -ENOMEM;
			sg_init_one(&sg, sector, 512);
			ret = sd_command(host, &read);
			if (ret) {
				kfree(sector);
				return ret;
			}
			dev_info(mmc_dev(host->mmc), "Sector-zero read: crc32=%08x signature=%02x%02x\n",
				crc32_le(~0U, sector, 512) ^ ~0U, sector[510], sector[511]);
			kfree(sector);
		}
	}
	if (data && !writing) {
		/* Wider transfers must reject CRC7/CRC16, CRC timeout and invalid
		 * responses before exposing any data to the block layer. */
		if ((readb(host->regs + ST1) & 0xc2) ||
		    (readb(host->regs + ST2) & 3) || sd_write_status_error(cmd->resp[0])) {
			sd_freeze(host);
			cmd->retries = 0;
			return -EILSEQ;
		}
		/* AUTO_READ1 payload remains private until checked READY/TRAN. */
		if (cmd->opcode == 18)
			return 0;
		stage_ns = sd_now();
		if (sg_copy_from_buffer(data->sg, data->sg_len, host->buffer, bytes) != bytes)
			return -EIO;
		sd_elapsed(host, SD_COPY_NS, stage_ns);
		data->bytes_xfered = bytes;
	}
	/* Successful stream stops are per-request traffic; keep the boot log.
	 * Failures are still reported above and request counters remain intact.
	 */
	if (cmd->opcode != 12 && cmd->opcode != 17 && cmd->opcode != 18 && cmd->opcode != 24 && cmd->opcode != 25 && cmd->opcode != 13)
		dev_info(mmc_dev(host->mmc), "CMD%u arg=%08x resp=%08x bytes=%u\n",
			cmd->opcode, cmd->arg, cmd->resp[0], bytes);
	return 0;
}

static int sd_command(struct sd_probe *host, struct mmc_command *cmd)
{
	u64 start = sd_now();
	int ret = sd_command_inner(host, cmd);
	if (start && (cmd->opcode == 17 || cmd->opcode == 18)) {
		sd_count(host, SD_READ_COMMANDS, 1);
		if (cmd->opcode == 18)
			sd_count(host, SD_STREAM_COMMANDS, 1);
		sd_elapsed(host, SD_READ_COMMAND_NS, start);
	}
	if (start && (cmd->opcode == 24 || cmd->opcode == 25)) {
		sd_count(host, SD_WRITE_COMMANDS, 1);
		if (cmd->opcode == 25)
			sd_count(host, SD_WRITE_STREAM_COMMANDS, 1);
		sd_elapsed(host, SD_WRITE_COMMAND_NS, start);
	}
	return ret;
}

static void sd_native_write(struct sd_probe *host, struct mmc_request *mrq)
{
	struct mmc_command stop = {
		.opcode = MMC_STOP_TRANSMISSION, .arg = 0,
		.flags = MMC_RSP_R1B | MMC_CMD_AC,
	};
	struct mmc_data *data = mrq->data;
	struct mmc_command before_stop = {
		.opcode = MMC_SEND_STATUS,
		.flags = MMC_RSP_R1 | MMC_CMD_AC,
	};
	u32 status = 0;
	int ret = -EINVAL;

	if (data)
		data->bytes_xfered = 0;
	if (mrq->stop)
		mrq->stop->error = -ECANCELED;
	if (!native_write || mrq->cmd->opcode != MMC_WRITE_MULTIPLE_BLOCK ||
	    !data || mrq->cmd->data != data ||
	    data->flags != MMC_DATA_WRITE || data->blksz != 512 ||
	    !data->blocks || data->blocks > SD_BUFFER_BYTES / 512)
		goto done;
	ret = -EROFS;
	if (!sd_write_permitted(host, mrq->cmd->arg, data->blocks))
		goto done;
	ret = sd_command(host, mrq->cmd);
	if (ret || host->failed) {
		if (!ret)
			ret = -EIO;
		goto done;
	}
	/* One status query distinguishes an open stream from a controller that
	 * already terminated it. This is not a wait for TRAN before CMD12.
	 * Never accept/clear an error R1 just to make a write appear successful.
	 */
	before_stop.arg = host->mmc->card->rca << 16;
	ret = sd_command(host, &before_stop);
	status = before_stop.resp[0];
	if (!ret && sd_write_status_error(status))
		ret = -EIO;
	if (ret) {
		dev_err(mmc_dev(host->mmc), "CMD25 pre-stop status failed: r1=%08x error=%d\n", status, ret);
		sd_freeze(host);
		goto done;
	}
	if (((status >> 9) & 15) == 4) {
		/* READY/TRAN already confirms programming. An extra CMD12 can be
		 * rejected by a card whose multiwrite stream has already ended.
		 */
		if (!sd_write_status_ready(status))
			ret = sd_wait_programmed(host, &status);
		if (ret) {
			sd_freeze(host);
			goto done;
		}
		if (mrq->stop)
			mrq->stop->error = 0;
		goto completed;
	}
	if (((status >> 9) & 15) != 6 && ((status >> 9) & 15) != 7) {
		dev_err(mmc_dev(host->mmc), "CMD25 unexpected pre-stop state: r1=%08x\n", status);
		ret = -EIO;
		sd_freeze(host);
		goto done;
	}
	/* RCV/PRG: close the still-open stream, then wait for programming. */
	ret = sd_command(host, &stop);
	if (!ret && sd_write_status_error(stop.resp[0]))
		ret = -EIO;
	stop.error = ret;
	if (mrq->stop) {
		mrq->stop->error = ret;
		memcpy(mrq->stop->resp, stop.resp, sizeof(stop.resp));
	}
	if (!ret)
		ret = sd_wait_programmed(host, &status);
	if (ret) {
		dev_err(mmc_dev(host->mmc), "CMD25 completion failed: stop_error=%d stop_r1=%08x error=%d\n",
			stop.error, stop.resp[0], ret);
		sd_freeze(host);
		goto done;
	}
	/* AUTOWRITE1 skips the initial R1. Return the checked completion status,
	 * and acknowledge the entire burst only after programming has finished.
	 */
completed:
	mrq->cmd->resp[0] = status;
	if (mrq->stop)
		mrq->stop->resp[0] = status;
	data->bytes_xfered = data->blocks * 512;
done:
	mrq->cmd->error = ret;
	mrq->cmd->retries = 0;
	if (data)
		data->error = ret;
}

static int sd_wait_read_ready(struct sd_probe *host, u32 *response)
{
	unsigned long deadline = jiffies + msecs_to_jiffies(3000);

	do {
		struct mmc_command status = {
			.opcode = MMC_SEND_STATUS, .arg = host->mmc->card->rca << 16,
			.flags = MMC_RSP_R1 | MMC_CMD_AC,
		};
		int ret = sd_command(host, &status);
		u32 state = (status.resp[0] >> 9) & 15;

		if (ret)
			return ret;
		if (sd_write_status_error(status.resp[0]) || (state != 4 && state != 5))
			return -EIO;
		if (sd_write_status_ready(status.resp[0])) {
			*response = status.resp[0];
			return 0;
		}
		usleep_range(1000, 2000);
	} while (time_before(jiffies, deadline));
	return -ETIMEDOUT;
}

static void sd_native_read(struct sd_probe *host, struct mmc_request *mrq)
{
	struct mmc_data *data = mrq->data;
	struct mmc_command status_cmd = {
		.opcode = MMC_SEND_STATUS, .flags = MMC_RSP_R1 | MMC_CMD_AC,
	};
	struct mmc_command stop = {
		.opcode = MMC_STOP_TRANSMISSION, .flags = MMC_RSP_R1B | MMC_CMD_AC,
	};
	struct scatterlist *sg;
	unsigned int bytes, available = 0, n;
	u32 status = 0, state;
	int ret = -EINVAL;
	u64 stage_ns;

	if (data)
		data->bytes_xfered = 0;
	if (mrq->stop)
		mrq->stop->error = -ECANCELED;
	if (!data || mrq->cmd->data != data || data->flags != MMC_DATA_READ ||
	    data->blksz != 512 || !data->blocks || data->blocks > SD_BUFFER_BYTES / 512 ||
	    !data->sg || !data->sg_len)
		goto done;
	bytes = data->blocks * 512;
	for_each_sg(data->sg, sg, data->sg_len, n) {
		unsigned int take = sg->length < bytes - available ? sg->length : bytes - available;

		available += take;
		if (available == bytes)
			break;
	}
	if (available != bytes)
		goto done;
	ret = -EACCES;
	if (!sd_read_permitted(host, mrq->cmd->arg, data->blocks))
		goto done;
	ret = sd_command(host, mrq->cmd);
	if (ret || host->failed) {
		if (!ret)
			ret = -EIO;
		goto done;
	}
	/* CRC and DMA release are checked before any status or stop command.
	 * Non-data commands preserve the payload; callers cannot see it yet. */
	status_cmd.arg = host->mmc->card->rca << 16;
	ret = sd_command(host, &status_cmd);
	status = status_cmd.resp[0];
	state = (status >> 9) & 15;
	if (!ret && (sd_write_status_error(status) || (state != 4 && state != 5)))
		ret = -EIO;
	if (ret)
		goto uncertain;
	if (state == 5) {
		ret = sd_command(host, &stop);
		if (ret)
			goto uncertain;
		ret = sd_wait_read_ready(host, &status);
	} else if (!sd_write_status_ready(status)) {
		ret = sd_wait_read_ready(host, &status);
	}
	if (ret)
		goto uncertain;
	stage_ns = sd_now();
	if (sg_copy_from_buffer(data->sg, data->sg_len, host->buffer, bytes) != bytes) {
		ret = -EIO;
		goto done;
	}
	sd_elapsed(host, SD_COPY_NS, stage_ns);
	mrq->cmd->resp[0] = status;
	if (mrq->stop) {
		mrq->stop->error = 0;
		mrq->stop->resp[0] = status;
	}
	data->bytes_xfered = bytes;
	goto done;
uncertain:
	sd_freeze(host);
	dev_err(mmc_dev(host->mmc), "CMD18 completion uncertain: r1=%08x error=%d; frozen\n", status, ret);
done:
	mrq->cmd->error = ret;
	mrq->cmd->retries = 0;
	if (data)
		data->error = ret;
}

static void sd_work(struct work_struct *work)
{
	struct sd_probe *host = container_of(work, struct sd_probe, work);
	struct mmc_request *mrq = host->mrq;
	bool split_read = mrq->cmd->opcode == 18;
	u64 request_ns = sd_now(), stage_ns;
#ifdef BPI_M4_SD_PROFILE
	sd_elapsed(host, SD_QUEUE_NS, host->queued_ns);
#endif
	sd_count(host, SD_REQUESTS, 1);
	if (mrq->sbc) {
		mrq->sbc->error = -EOPNOTSUPP;
		mrq->cmd->error = -EOPNOTSUPP;
		mrq->cmd->retries = 0;
		if (mrq->data) {
			mrq->data->error = -EOPNOTSUPP;
			mrq->data->bytes_xfered = 0;
		}
		if (mrq->stop)
			mrq->stop->error = -ECANCELED;
	} else if (split_read && native_read) {
		sd_native_read(host, mrq);
	} else if (mrq->cmd->opcode == MMC_WRITE_MULTIPLE_BLOCK && native_write) {
		sd_native_write(host, mrq);
	} else if (mrq->cmd->opcode == MMC_WRITE_MULTIPLE_BLOCK) {
		struct mmc_data *data = mrq->data;
		u8 *page = NULL;
		unsigned int i;
		int ret = -EINVAL;

		if (data)
			data->bytes_xfered = 0;
		if (data && data->flags == MMC_DATA_WRITE && data->blksz == 512 &&
		    data->blocks && data->blocks <= SD_BUFFER_BYTES / 512) {
			ret = -EROFS;
			if (sd_write_permitted(host, mrq->cmd->arg, data->blocks)) {
				page = kmalloc(SD_BUFFER_BYTES, GFP_KERNEL);
				ret = page ? 0 : -ENOMEM;
			}
			if (!ret && sg_copy_to_buffer(data->sg, data->sg_len, page,
				data->blocks * 512) != data->blocks * 512)
				ret = -EIO;
			for (i = 0; !ret && i < data->blocks; i++) {
				struct scatterlist sg;
				struct mmc_data one = { .blksz = 512, .blocks = 1,
					.flags = MMC_DATA_WRITE, .sg = &sg, .sg_len = 1 };
				struct mmc_command cmd = { .opcode = MMC_WRITE_BLOCK,
					.arg = mrq->cmd->arg + i,
					.flags = MMC_RSP_R1 | MMC_CMD_ADTC, .data = &one };

				sg_init_one(&sg, page + i * 512, 512);
				ret = sd_command(host, &cmd);
				memcpy(mrq->cmd->resp, cmd.resp, sizeof(cmd.resp));
				if (!ret)
					data->bytes_xfered += 512;
			}
		}
		kfree(page);
		mrq->cmd->error = ret;
		mrq->cmd->retries = 0;
		if (data)
			data->error = ret;
		/* Each CMD24 terminates itself: no native CMD25 or CMD12. */
		if (mrq->stop)
			mrq->stop->error = 0;
	} else if (split_read) {
		struct mmc_data *data = mrq->data;
		u8 *page = NULL;
		unsigned int i = 0;
		int ret = -EINVAL;
		if (data)
			data->bytes_xfered = 0;
		/* Linux requires page-sized I/O; the controller still reads one sector. */
		if (data && data->flags & MMC_DATA_READ && !(data->flags & MMC_DATA_WRITE) &&
		    data->blksz == 512 && data->blocks && data->blocks <= SD_BUFFER_BYTES / 512) {
			stage_ns = sd_now();
			page = kmalloc(SD_BUFFER_BYTES, GFP_KERNEL);
			sd_elapsed(host, SD_ALLOC_NS, stage_ns);
			ret = page ? 0 : -ENOMEM;
			for (; !ret && i < data->blocks; i++) {
				struct scatterlist sg;
				struct mmc_data one = { .blksz = 512, .blocks = 1, .flags = MMC_DATA_READ, .sg = &sg, .sg_len = 1 };
				struct mmc_command cmd = { .opcode = 17, .arg = mrq->cmd->arg + i,
					.flags = MMC_RSP_R1 | MMC_CMD_ADTC, .data = &one };
				sg_init_one(&sg, page + i * 512, 512);
				ret = sd_command(host, &cmd);
				memcpy(mrq->cmd->resp, cmd.resp, sizeof(cmd.resp));
			}
			if (!ret) {
				unsigned int bytes = data->blocks * 512;
				stage_ns = sd_now();
				if (sg_copy_from_buffer(data->sg, data->sg_len, page, bytes) != bytes)
					ret = -EIO;
				else
					data->bytes_xfered = bytes;
				sd_elapsed(host, SD_COPY_NS, stage_ns);
			}
		}
		kfree(page);
		mrq->cmd->error = ret;
		if (data)
			data->error = ret;
		/* Each CMD17 terminates itself; no CMD18 stream or CMD12 is sent. */
		if (mrq->stop)
			mrq->stop->error = 0;
	} else {
		mrq->cmd->error = sd_command(host, mrq->cmd);
		if (mrq->data)
			mrq->data->error = mrq->cmd->error;
		if (mrq->stop && !mrq->cmd->error)
			mrq->stop->error = sd_command(host, mrq->stop);
	}
	mrq->cmd->retries = 0;
	if (mrq->cmd->error || (mrq->data && mrq->data->error) ||
	    (mrq->stop && mrq->stop->error))
		sd_count(host, SD_REQUEST_ERRORS, 1);
	if (mrq->data)
		sd_count(host, SD_REQUEST_BYTES, mrq->data->bytes_xfered);
	sd_elapsed(host, SD_REQUEST_NS, request_ns);
	host->mrq = NULL;
	mmc_request_done(host->mmc, mrq);
}
static void sd_request(struct mmc_host *mmc, struct mmc_request *mrq)
{
	struct sd_probe *host = mmc_priv(mmc);
#ifdef BPI_M4_SD_PROFILE
	host->queued_ns = sd_now();
#endif
	host->mrq = mrq;
	queue_work(system_long_wq, &host->work);
}
static void sd_ios(struct mmc_host *mmc, struct mmc_ios *ios)
{
	struct sd_probe *host = mmc_priv(mmc);
	/* 50 MHz is allowed only after the core switches the card to SD HS. */
	u32 next_clock = ios->timing == MMC_TIMING_SD_HS && ios->clock >= 50000000 ?
		0x2100 : ios->clock >= 25000000 ? 0x2101 : 0x2103;
	if (host->data_clock != next_clock && next_clock == 0x2100)
		dev_info(mmc_dev(mmc), "Experimental 50 MHz SD high-speed clock enabled\n");
	else if (host->data_clock != next_clock && next_clock == 0x2101)
		dev_info(mmc_dev(mmc), "Experimental 25 MHz legacy SD data clock enabled\n");
	host->data_clock = next_clock;
	writel(ios->clock > 400000 ? host->data_clock : 0x2100, host->regs + CKGEN);
	host->bus_bits = ios->bus_width == MMC_BUS_WIDTH_4 ? 1 : 0;
	writeb((ios->clock > 400000 ? 0x10 : 0xd0) | host->bus_bits, host->regs + CFG1);
	mmc->actual_clock = next_clock == 0x2100 && ios->clock > 400000 ? 50000000 :
		ios->clock >= 25000000 ? 25000000 :
		ios->clock > 400000 ? 6250000 : 390625;
	sd_sync(host);
}
static int sd_ro(struct mmc_host *mmc)
{
	/* CID is checked again per write after the core has attached the card. */
	return !write_enable;
}
static int sd_cd(struct mmc_host *mmc)
{
	struct sd_probe *host = mmc_priv(mmc);
	return !!(readb(host->regs + EXIST) & 4);
}
static const struct mmc_host_ops sd_ops = {
	.request = sd_request, .set_ios = sd_ios, .get_ro = sd_ro, .get_cd = sd_cd,
};

static int sd_probe(struct platform_device *pdev)
{
	struct mmc_host *mmc;
	struct sd_probe *host;
	void __iomem *crt;
	if (native_read && (!read_cid || strlen(read_cid) != 32 ||
	    strspn(read_cid, "0123456789abcdef") != 32 || !read_capacity ||
	    read_capacity > 0x100000000ULL))
		return dev_err_probe(&pdev->dev, -EINVAL, "Explicit read CID/capacity required\n");
	if (write_enable && (!sd_write_range_valid(scratch_start, scratch_sectors) ||
	    !scratch_cid || strlen(scratch_cid) != 32 ||
	    strspn(scratch_cid, "0123456789abcdef") != 32))
		return dev_err_probe(&pdev->dev, -EINVAL, "Explicit scratch range and CID required\n");
	if (!of_machine_is_compatible("bananapi,bpi-m4"))
		return -ENODEV;
	crt = devm_ioremap(&pdev->dev, 0x98000000, 0x400);
	if (!crt || readl(crt + 0x1e0) != 0x2003 || readl(crt + 0x1e8) != 0x00564388)
		return dev_err_probe(&pdev->dev, -EINVAL, "Unverified SD voltage/clock state\n");
	mmc = devm_mmc_alloc_host(&pdev->dev, sizeof(*host));
	if (!mmc)
		return -ENOMEM;
	host = mmc_priv(mmc);
	host->mmc = mmc;
	host->data_clock = 0x2103;
	host->regs = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(host->regs))
		return PTR_ERR(host->regs);
	host->bridge = devm_ioremap(&pdev->dev, 0x9801a020, 4);
	if (!host->bridge)
		return -ENOMEM;
	if (!(readb(host->regs + EXIST) & 4))
		return -ENOMEDIUM;
	if (dma_set_mask_and_coherent(&pdev->dev, DMA_BIT_MASK(32)))
		return -EINVAL;
	host->buffer = dmam_alloc_coherent(&pdev->dev, SD_BUFFER_BYTES, &host->dma, GFP_KERNEL);
	if (!host->buffer || host->dma & 7)
		return -ENOMEM;
	INIT_WORK(&host->work, sd_work);
	mmc->ops = &sd_ops;
	mmc->f_min = 400000;
	mmc->f_max = 50000000;
	mmc->ocr_avail = MMC_VDD_32_33 | MMC_VDD_33_34;
	mmc->caps = MMC_CAP_NONREMOVABLE | MMC_CAP_SD_HIGHSPEED | MMC_CAP_4_BIT_DATA;
	mmc->caps2 = MMC_CAP2_NO_SDIO | MMC_CAP2_NO_MMC;
	mmc->max_blk_size = 512;
	mmc->max_blk_count = SD_BUFFER_BYTES / 512;
	mmc->max_req_size = SD_BUFFER_BYTES;
	mmc->max_seg_size = SD_BUFFER_BYTES;
	/* Copy up to sixteen ordinary pages into the coherent DMA buffer.
	 * Keeping max_segs=1 would prevent typical file I/O from merging. */
	mmc->max_segs = SD_BUFFER_BYTES / PAGE_SIZE;
	platform_set_drvdata(pdev, host);
#ifdef BPI_M4_SD_PROFILE
	{
		int ret = devm_device_add_group(&pdev->dev, &sd_profile_group);
		if (ret)
			return ret;
	}
	dev_info(&pdev->dev, "SD profiling candidate; polling interval %u us\n", poll_us);
#endif
	/* Disable L4 gating and reset inherited DMA/FIFO state before CMD0. */
	writel(readl(host->regs + SYNC) | 2, host->regs + SYNC);
	sd_abort(host);
	writeb(readb(host->regs + CFG1) & ~0x10, host->regs + CFG1);
	udelay(100);
	/* BSP legacy setup: enable the SD output and clock, not SDIO/MS. */
	writeb(0, host->regs + STOP);
	writeb(2, host->regs + CARD_SELECT);
	writeb(4, host->regs + CARD_OE);
	writeb(4, host->regs + CARD_CLOCK);
	dev_info(&pdev->dev, "BPI-M4 CID-bound CMD18/CMD25 candidate; inherited power; polling\n");
	return mmc_add_host(mmc);
}
static void sd_remove(struct platform_device *pdev)
{
	struct sd_probe *host = platform_get_drvdata(pdev);
	mmc_remove_host(host->mmc);
	cancel_work_sync(&host->work);
	sd_abort(host);
}
static struct platform_driver sd_driver = {
	.probe = sd_probe, .remove = sd_remove, .driver = { .name = "bpi-m4-sd-cmd18" },
};
static int __init sd_init(void)
{
	struct resource resource = DEFINE_RES_MEM(0x98010400, 0x200);
	int ret = platform_driver_register(&sd_driver);
	if (ret)
		return ret;
	probe_device = platform_device_register_simple("bpi-m4-sd-cmd18", -1, &resource, 1);
	if (IS_ERR(probe_device)) {
		platform_driver_unregister(&sd_driver);
		return PTR_ERR(probe_device);
	}
	return 0;
}
static void __exit sd_exit(void)
{
	platform_device_unregister(probe_device);
	platform_driver_unregister(&sd_driver);
}
module_init(sd_init);
module_exit(sd_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Experimental CID/range-gated BPI-M4 SD write host");
