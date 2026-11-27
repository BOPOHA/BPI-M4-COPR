// SPDX-License-Identifier: GPL-2.0
/*
 * Realtek RTD1295/RTD1296 eMMC host
 *
 * The controller is a Synopsys DesignWare MSHC (VERID 2.70a, internal DMAC,
 * 32-bit descriptors) with a Realtek wrapper at +0x400. Commands work as
 * dw_mmc expects; its DMAC and what is around it do not:
 *
 *  - The bus bridge (SB2) holds CPU writes back from DDR until it is told
 *    to sync. Descriptors the DMAC fetches without that are the previous
 *    ones.
 *  - After the last descriptor the DMAC still follows the next pointer and
 *    takes whatever descriptor it finds there that says OWN -- and it never
 *    hands a descriptor back, so old ones keep saying it. It stays parked
 *    there, and DBADDR does not move it.
 *  - Data-transfer-over comes when the card is done; on a read the DMAC is
 *    still emptying the FIFO into DDR then.
 *  - The data-busy status does not clear after an R1b command.
 *
 * Each of these turned into DMA to stale buffers, freed memory or random
 * addresses, i.e. memory corruption and resets of the SoC. So this driver
 * does it the way Realtek's BSP and u-boot do (rtkemmc.c), plus what they
 * get away without: fresh descriptors for every transfer behind a sync,
 * ended on one the DMAC does not own; the DMAC restarted from DBADDR for
 * every transfer; reads complete only once the DMAC has moved every byte
 * and the wrapper says DMA_DONE; and busy left to the MMC core's CMD13
 * polling.
 *
 * BPI-M4 pilot: explicitly activated, read-only, at most one page per read,
 * one-bit legacy timing <=20 MHz. RTD1395 VERID/HCON and the inherited
 * 200 MHz firmware PLL are checked before controller writes. Firmware pad
 * voltage and phases are retained. No PLL programming, tuning or HS200.
 * DMA failure freezes the host and retains the bounce buffer until reset.
 */
#include <linux/bitfield.h>
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/mmc/host.h>
#include <linux/mmc/mmc.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/mfd/syscon.h>
#include <linux/regmap.h>
#include <linux/workqueue.h>
#include "../core/card.h"

/* DesignWare core */
#define EM_CTRL			0x000
#define  CTRL_RESET		BIT(0)
#define  CTRL_FIFO_RESET	BIT(1)
#define  CTRL_DMA_RESET		BIT(2)
#define  CTRL_INT_ENABLE	BIT(4)
#define  CTRL_USE_IDMAC		BIT(25)
#define  CTRL_RESETS		(CTRL_RESET | CTRL_FIFO_RESET | CTRL_DMA_RESET)
#define EM_PWREN		0x004
#define EM_CLKDIV		0x008
#define EM_CLKSRC		0x00c
#define EM_CLKENA		0x010
#define EM_TMOUT		0x014
#define EM_CTYPE		0x018
#define  CTYPE_4BIT		BIT(0)
#define  CTYPE_8BIT		BIT(16)
#define EM_BLKSIZ		0x01c
#define EM_BYTCNT		0x020
#define EM_INTMASK		0x024
#define EM_CMDARG		0x028
#define EM_CMD			0x02c
#define  CMD_START		BIT(31)
#define  CMD_USE_HOLD_REG	BIT(29)
#define  CMD_UPD_CLK		BIT(21)
#define  CMD_INIT		BIT(15)
#define  CMD_STOP		BIT(14)
#define  CMD_AUTO_STOP		BIT(12)
#define  CMD_PRV_DAT_WAIT	BIT(13)
#define  CMD_DAT_WR		BIT(10)
#define  CMD_DAT_EXP		BIT(9)
#define  CMD_RESP_CRC		BIT(8)
#define  CMD_RESP_LONG		BIT(7)
#define  CMD_RESP_EXP		BIT(6)
#define EM_RESP0		0x030
#define EM_RESP1		0x034	/* the auto-stop's response */
#define EM_MINTSTS		0x040
#define EM_RINTSTS		0x044
#define  INT_RE			BIT(1)
#define  INT_CD			BIT(2)
#define  INT_DTO		BIT(3)
#define  INT_RCRC		BIT(6)
#define  INT_DCRC		BIT(7)
#define  INT_RTO		BIT(8)
#define  INT_DRTO		BIT(9)
#define  INT_HTO		BIT(10)
#define  INT_FRUN		BIT(11)
#define  INT_HLE		BIT(12)
#define  INT_SBE		BIT(13)
#define  INT_ACD		BIT(14)	/* auto-stop done */
#define  INT_EBE		BIT(15)
#define  INT_CMD_ERR		(INT_RE | INT_RCRC | INT_RTO | INT_HLE)
#define  INT_DATA_ERR		(INT_DCRC | INT_DRTO | INT_HTO | INT_FRUN | \
				 INT_SBE | INT_EBE)
#define EM_STATUS		0x048
#define  STATUS_FIFO_COUNT	GENMASK(29, 17)
#define EM_TBBCNT		0x060	/* bytes between memory and the FIFO */
#define EM_FIFOTH		0x04c
#define EM_UHS_REG		0x074
#define  UHS_18V		BIT(0)
#define EM_BMOD			0x080
#define  BMOD_SWR		BIT(0)
#define  BMOD_DE		BIT(7)
#define EM_DBADDR		0x088
#define EM_IDSTS		0x08c
#define EM_IDINTEN		0x090
#define EM_CARDTHRCTL		0x100
#define EM_DATA			0x200	/* the FIFO */

/* Realtek wrapper */
#define EM_ISR			0x424
#define  ISR_WRITE_DATA		BIT(0)	/* 1: set the bits given, 0: clear */
#define  ISR_DMA_DONE		BIT(1)
#define  ISR_DMA_INT_MASK	BIT(2)
#define  ISR_DESC_INT_MASK	BIT(3)
#define  ISR_IP_INT_MASK	BIT(4)
#define EM_CP			0x41c
#define EM_SWC_SEL		0x4d4

/* 32-bit IDMAC descriptors, chained */
struct em_desc {
	__le32 des0;
#define DES0_OWN		BIT(31)
#define DES0_CH			BIT(4)
#define DES0_FS			BIT(3)
#define DES0_LD			BIT(2)
#define DES0_DIC		BIT(1)
	__le32 des1;		/* buffer size */
	__le32 des2;		/* buffer address */
	__le32 des3;		/* next descriptor */
};

#define EM_DESC_LEN		4096		/* per descriptor, as the BSP */
#define EM_NR_DESC		2
#define EM_TIMEOUT_MS		2000
#define EM_TUNING_TIMEOUT_MS	50

/* SB2, the bus bridge: writing SYNC drains the CPU's posted writes to DDR */
#define SB2_SYNC		0x020

/* CRT: the EMMC PLL */
#define CRT_PLL_EMMC1		0x1f0
#define  PLL_TX_PHASE		GENMASK(7, 3)
#define  PLL_RX_PHASE		GENMASK(12, 8)
#define  PLL_RSTB		BIT(1)
#define CRT_PLL_EMMC3		0x1f8	/* bits 31:16 frequency code */
#define CRT_PLL_EMMC4		0x1fc	/* bit 0 output enable */
#define EM_PLL_100MHZ		0x57	/* the BSP's codes */
#define EM_PLL_200MHZ		0xa6
#define EM_NR_PHASES		32
#define EM_OTHER1		0x420
#define  OTHER1_L4_GATE		BIT(3)
#define EM_DUMMY_SYS		0x42c
#define EM_CKGEN_CTL		0x478
#define  CKGEN_CLK_4MHZ		GENMASK(18, 16)	/* off the PLL, to 4 MHz */
#define EM_DDR_REG		0x10c
#define EM_DQS_CTRL1		0x498

enum em_state { ST_IDLE, ST_CMD, ST_DATA, ST_STOP };

struct em_host {
	struct device *dev;
	struct mmc_host *mmc;
	void __iomem *base;
	unsigned long bus_hz;
	u32 clock;			/* the card clock set, Hz */

	struct regmap *sb2;
	struct regmap *crt;
	struct clk *clk_ip;
	struct em_desc *desc;
	dma_addr_t desc_dma;

	spinlock_t lock;
	struct mmc_request *mrq;
	struct mmc_command *cmd;	/* the command in flight */
	enum em_state state;
	struct mmc_request *done;	/* to report once the lock is dropped */
	u32 rint;			/* status collected by the hard irq */
	u32 got, need;			/* data phase: seen, and needed to end */
	u32 last_rint;
	int sg_count;
	int nr_desc;
	struct delayed_work timeout;
	bool rtd1395;
	bool failed, dma_active;
	void *bounce;
	dma_addr_t bounce_dma;
};

static bool activate;
module_param(activate, bool, 0444);
MODULE_PARM_DESC(activate, "Explicitly activate the unvalidated read-only BPI-M4 eMMC pilot");

/* Initialization permits only two volatile EXT_CSD controls. No partition switch. */
static bool em_allowed(struct mmc_request *mrq)
{
 struct mmc_data *d = mrq->data;
 if (d && (d->flags != MMC_DATA_READ || d->blksz != 512 || !d->blocks ||
           d->blocks > PAGE_SIZE / 512))
  return false;
 if (mrq->stop && (mrq->stop->opcode != MMC_STOP_TRANSMISSION || mrq->stop->arg))
  return false;
 if (mrq->sbc && (!d || mrq->cmd->opcode != MMC_READ_MULTIPLE_BLOCK ||
                 mrq->sbc->opcode != MMC_SET_BLOCK_COUNT || mrq->sbc->arg != d->blocks))
  return false;
 switch (mrq->cmd->opcode) {
 case 0: case 1: case 2: case 3: case 7: case 9: case 13: case 16:
  return !d && !mrq->sbc;
 case 6: {
  u32 arg = mrq->cmd->arg;
  u32 index = (arg >> 16) & 255, value = (arg >> 8) & 255;
  return !d && !mrq->sbc && (arg >> 24) == MMC_SWITCH_MODE_WRITE_BYTE &&
   (arg & 255) == EXT_CSD_CMD_SET_NORMAL && value == 1 &&
   (index == EXT_CSD_ERASE_GROUP_DEF || index == EXT_CSD_POWER_OFF_NOTIFICATION);
 }
 case 8:
  return d && d->blocks == 1 && !mrq->sbc;
 case 17:
  return d && d->blocks == 1 && !mrq->sbc;
 case 18:
  return d;
 default:
  return false;
 }
}

static void em_release_dma(void *data)
{
 struct em_host *h = data;
 if (h->failed || h->dma_active) {
  dev_warn(h->dev, "uncertain DMA: retaining coherent buffers until physical reset\n");
  return;
 }
 dma_free_coherent(h->dev, PAGE_SIZE, h->bounce, h->bounce_dma);
 dma_free_coherent(h->dev, EM_NR_DESC * sizeof(*h->desc), h->desc, h->desc_dma);
}

static u32 em_read(struct em_host *h, u32 reg)
{
	return readl(h->base + reg);
}

static void em_write(struct em_host *h, u32 reg, u32 val)
{
	writel(val, h->base + reg);
}

static int em_reset(struct em_host *h, u32 bits)
{
	u32 val;

	em_write(h, EM_CTRL, em_read(h, EM_CTRL) | bits);
	return readl_poll_timeout_atomic(h->base + EM_CTRL, val,
					 !(val & bits), 1, 500000);
}

/* Send a command that only updates the card clock */
static int em_update_clock(struct em_host *h)
{
	u32 val;

	em_write(h, EM_CMD, CMD_START | CMD_USE_HOLD_REG | CMD_UPD_CLK);
	return readl_poll_timeout_atomic(h->base + EM_CMD, val,
					 !(val & CMD_START), 1, 500000);
}

/*
 * The whole controller, DMAC and state machines, back to idle; the clock
 * logic has to be told again after that, as dw_mmc does.
 */
static void __maybe_unused em_full_reset(struct em_host *h)
{
	em_reset(h, CTRL_RESETS);
	if (em_update_clock(h)) { h->failed = true; return; }
}

static void em_set_clock(struct em_host *h, unsigned int clock)
{
	u32 div;

	if (clock == h->clock)
		return;
	/* the core divides by 2 * div; 0 passes the clock through */
	div = clock ? DIV_ROUND_UP(h->bus_hz, 2 * clock) : 0;
	if (clock && clock >= h->bus_hz)
		div = 0;

	em_write(h, EM_CLKENA, 0);
	if (em_update_clock(h)) { h->failed = true; return; }
	if (!clock) {
		h->clock = 0;
		return;
	}
	em_write(h, EM_CLKDIV, div);
	if (em_update_clock(h)) { h->failed = true; return; }
	/* enable; bit 16 would gate the clock when idle */
	em_write(h, EM_CLKENA, BIT(0));
	if (em_update_clock(h)) { h->failed = true; return; }
	h->clock = clock;
	dev_dbg(h->dev, "card clock %u Hz (div %u)\n",
		div ? (u32)(h->bus_hz / (2 * div)) : (u32)h->bus_hz, div);
}

static void em_hw_init(struct em_host *h)
{
	/* the wrapper: pass only the core's interrupt */
	writel(ISR_WRITE_DATA | ISR_DMA_INT_MASK | ISR_DESC_INT_MASK,
	       h->base + EM_ISR);
	writel(ISR_DMA_DONE, h->base + EM_ISR);
	writel(ISR_IP_INT_MASK, h->base + EM_ISR);
	writel(0, h->base + EM_SWC_SEL);
	writel(0, h->base + EM_CP);

	/* As the BSP's mmc_host_reset(), step for step */
	em_write(h, EM_BMOD, BMOD_SWR | BMOD_DE);
	em_write(h, EM_CTRL, CTRL_USE_IDMAC);
	em_write(h, EM_PWREN, 1);
	em_write(h, EM_INTMASK, 0);
	em_write(h, EM_RINTSTS, 0xffffffff);
	em_write(h, EM_CLKSRC, 0);
	em_write(h, EM_TMOUT, 0xffffff40);
	em_write(h, EM_CTYPE, 0);
	em_write(h, EM_FIFOTH, 0x0001007f);	/* single transfers */
	em_write(h, EM_CTRL, CTRL_USE_IDMAC | CTRL_INT_ENABLE);
	em_write(h, EM_BMOD, BMOD_DE);
	em_write(h, EM_DBADDR, h->desc_dma);
	em_write(h, EM_IDINTEN, 0);
	em_write(h, EM_IDSTS, 0xffffffff);
	em_write(h, EM_UHS_REG, UHS_18V);
	em_write(h, EM_CARDTHRCTL, 0x02000001);	/* read threshold, 512 B */
	h->clock = ~0;
	em_set_clock(h, 400000);
}

static int em_prepare_data(struct em_host *h, struct mmc_data *data)
{
 u32 val, len = data->blksz * data->blocks;
 int ret;
 if (data->flags != MMC_DATA_READ || !len || len > PAGE_SIZE)
  return -EROFS;
 memset(h->bounce, 0, PAGE_SIZE);
 memset(h->desc, 0, EM_NR_DESC * sizeof(*h->desc));
 h->desc[0].des0 = cpu_to_le32(DES0_OWN | DES0_CH | DES0_FS | DES0_LD | DES0_DIC);
 h->desc[0].des1 = cpu_to_le32(len);
 h->desc[0].des2 = cpu_to_le32(h->bounce_dma);
 h->desc[0].des3 = cpu_to_le32(h->desc_dma + sizeof(*h->desc));
 h->desc[1].des3 = cpu_to_le32(h->desc_dma + sizeof(*h->desc));
 h->nr_desc = 1;
 dma_wmb();
 ret = regmap_write(h->sb2, SB2_SYNC, 0);
 if (ret) return ret;
 dmb(sy);
 ret = em_reset(h, CTRL_DMA_RESET);
 if (ret) return ret;
 em_write(h, EM_BMOD, BMOD_SWR);
 ret = readl_poll_timeout_atomic(h->base + EM_BMOD, val, !(val & BMOD_SWR), 1, 1000);
 if (ret)
  return ret;
 em_write(h, EM_DBADDR, h->desc_dma);
 em_write(h, EM_BMOD, BMOD_DE);
 writel(0, h->base + EM_SWC_SEL);
 writel(0, h->base + EM_CP);
 em_write(h, EM_BLKSIZ, data->blksz);
 em_write(h, EM_BYTCNT, len);
 h->dma_active = true;
 return 0;
}

static void em_finish(struct em_host *h);

static void em_start_cmd(struct em_host *h, struct mmc_command *cmd,
			 enum em_state state)
{
	struct mmc_data *data = state == ST_CMD ? cmd->data : NULL;
	u32 flags = CMD_START | CMD_USE_HOLD_REG | cmd->opcode;

	if (cmd->opcode == MMC_GO_IDLE_STATE)
		flags |= CMD_INIT;
	if (state == ST_STOP)
		flags |= CMD_STOP;
	if (cmd->flags & MMC_RSP_PRESENT) {
		flags |= CMD_RESP_EXP;
		if (cmd->flags & MMC_RSP_136)
			flags |= CMD_RESP_LONG;
	}
	if (cmd->flags & MMC_RSP_CRC)
		flags |= CMD_RESP_CRC;
	if (data) {
		flags |= CMD_DAT_EXP;
		/*
		 * As the BSP: only block reads wait for the previous data to
		 * be over. A command that waits while the core still believes
		 * DAT0 busy -- it does after an R1b -- never starts.
		 */
		if (data->flags & MMC_DATA_WRITE)
			flags |= CMD_DAT_WR;
		else if (cmd->opcode != MMC_SEND_EXT_CSD)
			flags |= CMD_PRV_DAT_WAIT;
		/* without CMD23, the core sends CMD12 by itself */
		h->need = INT_DTO;
		if (data->stop && !h->mrq->sbc) {
			flags |= CMD_AUTO_STOP;
			h->need |= INT_ACD;
		}
		h->got = 0;
  if (em_prepare_data(h, data)) {
   h->failed = true;
   h->mrq->cmd->error = data->error = -EIO;
   em_finish(h);
   return;
  }
	}

	h->cmd = cmd;
	h->state = state;
	h->rint = 0;
	em_write(h, EM_RINTSTS, 0xffffffff);
	writel(ISR_DMA_DONE, h->base + EM_ISR);
	em_write(h, EM_INTMASK, INT_CD | INT_CMD_ERR |
		 (data ? h->need | INT_DATA_ERR : 0));
	em_write(h, EM_CMDARG, cmd->arg);
	wmb();
	em_write(h, EM_CMD, flags);
	/*
	 * A tuning block sampled at a bad phase can leave the data state
	 * machine waiting for good without the data timeout ever coming; the
	 * reset in em_end_data() gets it out.
	 */
	schedule_delayed_work(&h->timeout, msecs_to_jiffies(
			      cmd->opcode == MMC_SEND_TUNING_BLOCK_HS200 ?
			      EM_TUNING_TIMEOUT_MS : EM_TIMEOUT_MS));
}

static void em_read_resp(struct em_host *h, struct mmc_command *cmd)
{
	if (!(cmd->flags & MMC_RSP_PRESENT))
		return;
	if (cmd->flags & MMC_RSP_136) {
		cmd->resp[3] = em_read(h, EM_RESP0);
		cmd->resp[2] = em_read(h, EM_RESP0 + 4);
		cmd->resp[1] = em_read(h, EM_RESP0 + 8);
		cmd->resp[0] = em_read(h, EM_RESP0 + 12);
	} else {
		cmd->resp[0] = em_read(h, EM_RESP0);
	}
}

static void em_finish(struct em_host *h)
{
	struct mmc_request *mrq = h->mrq;

	cancel_delayed_work(&h->timeout);
	em_write(h, EM_INTMASK, 0);
	dev_dbg(h->dev, "CMD%u arg %08x: %d resp %08x%s data %d rint %08x status %08x\n",
		mrq->cmd->opcode, mrq->cmd->arg, mrq->cmd->error, mrq->cmd->resp[0],
		mrq->data ? "" : " (none)", mrq->data ? mrq->data->error : 0,
		h->last_rint, em_read(h, EM_STATUS));
	h->mrq = NULL;
	h->cmd = NULL;
	h->state = ST_IDLE;
	h->done = mrq;
}

/* With h->lock held on entry; drops it */
static void em_unlock_and_report(struct em_host *h, unsigned long flags)
{
	struct mmc_request *mrq = h->done;

	h->done = NULL;
	spin_unlock_irqrestore(&h->lock, flags);
	if (mrq)
		mmc_request_done(h->mmc, mrq);
}

static void em_end_data(struct em_host *h, struct mmc_data *data, int err)
{
 if (err) {
  /* No unmapping of caller SG or freeing uncertain DMA destinations. */
  h->failed = true;
  em_write(h, EM_INTMASK, 0);
  em_write(h, EM_BMOD, 0);
  dev_err(h->dev, "eMMC DMA error: host frozen; physical reset required\n");
 } else {
  dma_rmb();
  h->dma_active = false;
  h->desc[0].des0 = 0;
  if (sg_copy_from_buffer(data->sg, data->sg_len, h->bounce,
                           data->blksz * data->blocks) != data->blksz * data->blocks)
   err = -EFAULT;
 }
 data->error = err;
 data->bytes_xfered = err ? 0 : data->blksz * data->blocks;
 if (data->stop)
  data->stop->error = err;
 em_finish(h);
}

/*
 * Data-transfer-over is the card's side. On a read the DMAC may still be
 * emptying the FIFO into DDR then, and the data is not there to read, nor
 * may the next transfer start. It is done once it has moved every byte and
 * the wrapper has raised DMA_DONE -- which the BSP and u-boot wait for, but
 * which comes for every descriptor. A write's data has all been read by
 * the time the card has it.
 */
static int em_wait_dma(struct em_host *h, struct mmc_data *data)
{
	u32 total = data->blksz * data->blocks, isr;
	int ret;

	if (data->flags & MMC_DATA_WRITE)
		return 0;
	ret = read_poll_timeout_atomic(readl, isr, (isr & ISR_DMA_DONE) &&
				       em_read(h, EM_TBBCNT) == total,
				       1, 5000, false, h->base + EM_ISR);
 dma_rmb();
 /* This wrapper leaves OWN set; completion uses DMA_DONE plus byte count. */
	writel(ISR_DMA_DONE, h->base + EM_ISR);
	if (ret) {
		dev_err(h->dev, "read DMA not done: %u of %u bytes, ISR %08x\n",
			em_read(h, EM_TBBCNT), total, isr);
		return -EIO;
	}
	return 0;
}

/* Runs the request on from what the hard irq or the timeout found */
static void em_advance(struct em_host *h, u32 rint, bool timeout)
{
	struct mmc_command *cmd = h->cmd;
	struct mmc_data *data = cmd ? cmd->data : NULL;

	switch (h->state) {
	case ST_CMD:
		if (timeout || (rint & INT_CMD_ERR)) {
			cmd->error = timeout ? -ETIMEDOUT :
				     rint & INT_RTO ? -ETIMEDOUT : -EILSEQ;
			if (data) {
				em_end_data(h, data, cmd->error);
				return;
			}
			h->failed = true;
			em_finish(h);
			return;
		}
		if (!(rint & INT_CD))
			return;
		em_read_resp(h, cmd);
		if (cmd == h->mrq->sbc) {
			em_start_cmd(h, h->mrq->cmd, ST_CMD);
			return;
		}
		if (!data) {
			em_finish(h);
			return;
		}
		h->state = ST_DATA;
		fallthrough;
	case ST_DATA:
		if (timeout || (rint & INT_DATA_ERR)) {
			em_end_data(h, data, timeout ? -ETIMEDOUT :
				    rint & (INT_DRTO | INT_HTO) ? -ETIMEDOUT :
				    -EILSEQ);
			return;
		}
		h->got |= rint;
		if ((h->got & h->need) != h->need)
			return;
		if (data->stop && !h->mrq->sbc)
			data->stop->resp[0] = em_read(h, EM_RESP1);
		em_end_data(h, data, em_wait_dma(h, data));
		return;
	case ST_STOP:
		if (timeout || (rint & INT_CMD_ERR))
			cmd->error = -ETIMEDOUT;
		else if (!(rint & INT_CD))
			return;
		else
			em_read_resp(h, cmd);
		em_finish(h);
		return;
	case ST_IDLE:
		return;
	}
}

static irqreturn_t em_irq(int irq, void *dev_id)
{
	struct em_host *h = dev_id;
	u32 rint = em_read(h, EM_RINTSTS) & em_read(h, EM_INTMASK);

	if (!rint)
		return IRQ_NONE;
	em_write(h, EM_RINTSTS, rint);
	spin_lock(&h->lock);
	h->rint |= rint;
	spin_unlock(&h->lock);
	return IRQ_WAKE_THREAD;
}

static irqreturn_t em_irq_thread(int irq, void *dev_id)
{
	struct em_host *h = dev_id;
	unsigned long flags;
	u32 rint;

	spin_lock_irqsave(&h->lock, flags);
	rint = h->rint;
	h->rint = 0;
	h->last_rint = rint;
	if (h->mrq)
		em_advance(h, rint, false);
	em_unlock_and_report(h, flags);
	return IRQ_HANDLED;
}

static void em_timeout(struct work_struct *work)
{
	struct em_host *h = container_of(work, struct em_host, timeout.work);
	unsigned long flags;

	spin_lock_irqsave(&h->lock, flags);
	if (h->mrq) {
		dev_err(h->dev, "CMD%u timed out: RINTSTS %08x STATUS %08x IDSTS %08x\n",
			h->cmd->opcode, em_read(h, EM_RINTSTS),
			em_read(h, EM_STATUS), em_read(h, EM_IDSTS));
		em_advance(h, 0, true);
	}
	em_unlock_and_report(h, flags);
}

static void em_request(struct mmc_host *mmc, struct mmc_request *mrq)
{
	struct em_host *h = mmc_priv(mmc);
	unsigned long flags;

 if (mrq->data)
  mrq->data->bytes_xfered = 0;
 if (h->failed || !em_allowed(mrq)) {
  int error = h->failed ? -EIO : -EROFS;
  /* MMC core treats unsupported optional cache/HPI switches as EBADMSG. */
  if (!h->failed && mrq->cmd->opcode == MMC_SWITCH &&
      ((mrq->cmd->arg >> 16) & 255) != EXT_CSD_PART_CONFIG)
   error = -EBADMSG;
  mrq->cmd->error = error;
  if (mrq->data) mrq->data->error = error;
  if (mrq->sbc) mrq->sbc->error = error;
  if (mrq->stop) mrq->stop->error = error;
  mmc_request_done(mmc, mrq);
  return;
 }

	spin_lock_irqsave(&h->lock, flags);
	h->mrq = mrq;
	em_start_cmd(h, mrq->sbc ? mrq->sbc : mrq->cmd, ST_CMD);
	em_unlock_and_report(h, flags);
}

static void em_set_ios(struct mmc_host *mmc, struct mmc_ios *ios)
{
	struct em_host *h = mmc_priv(mmc);
 if (h->failed) return;
 if (ios->bus_width != MMC_BUS_WIDTH_1 || ios->clock > 20000000) {
  h->failed = true;
  return;
 }
 em_write(h, EM_CTYPE, 0);
 if (ios->power_mode != MMC_POWER_OFF)
  em_set_clock(h, ios->clock);

}

static int em_ro(struct mmc_host *mmc) { return 1; }

static void em_init_card(struct mmc_host *mmc, struct mmc_card *card)
{
 /* MMC initialization does not consult get_ro, unlike the SD path. */
 mmc_card_set_readonly(card);
 card->quirks |= MMC_QUIRK_BROKEN_HPI;
}

static const struct mmc_host_ops em_ops = {
	.request			= em_request,
	.set_ios			= em_set_ios,
	.get_ro = em_ro,
 .init_card = em_init_card,
	/* no card_busy: the core then polls with CMD13, as the BSP does */
};

static int em_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct mmc_host *mmc;
	struct em_host *h;
	struct clk *clk;
	int irq, ret;
	u32 val;

 if (!activate || !of_machine_is_compatible("bananapi,bpi-m4") ||
     !of_device_is_compatible(dev->of_node, "bananapi,bpi-m4-emmc-test"))
  return -ENODEV;
	mmc = devm_mmc_alloc_host(dev, sizeof(*h));
	if (!mmc)
		return -ENOMEM;
	h = mmc_priv(mmc);
	h->dev = dev;
	h->rtd1395 = of_device_is_compatible(dev->of_node,
					     "realtek,rtd1395-emmc");
	h->mmc = mmc;
	spin_lock_init(&h->lock);
	INIT_DELAYED_WORK(&h->timeout, em_timeout);

	h->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(h->base))
		return PTR_ERR(h->base);
	irq = platform_get_irq(pdev, 0);
	if (irq < 0)
		return irq;

 if (em_read(h, 0x6c) != 0x5342290a || em_read(h, 0x70) != 0x00c46d41)
  return dev_err_probe(dev, -EINVAL, "Unverified eMMC controller identity\n");
 /* Validate the inherited 200 MHz firmware PLL without reprogramming it. */
 h->crt = syscon_regmap_lookup_by_phandle(dev->of_node, "realtek,crt");
 if (IS_ERR(h->crt)) return PTR_ERR(h->crt);
 ret = regmap_read(h->crt, CRT_PLL_EMMC3, &val);
 if (ret) return ret;
 if (val != 0x00a64388 || readl(h->base + EM_CKGEN_CTL) != 0x2100)
  return dev_err_probe(dev, -EINVAL, "Unverified inherited eMMC clock\n");
 h->bus_hz = 200000000;
	/* CLK_EN1: EMMC (bus) and EMMC_IP (the core) */
	clk = devm_clk_get_optional_enabled(dev, "biu");
	if (IS_ERR(clk))
		return PTR_ERR(clk);
	h->clk_ip = devm_clk_get_optional_enabled(dev, "ip");
	if (IS_ERR(h->clk_ip))
		return PTR_ERR(h->clk_ip);

	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(32));
	if (ret)
		return ret;
	h->sb2 = syscon_regmap_lookup_by_phandle(dev->of_node, "realtek,sb2");
	if (IS_ERR(h->sb2))
		return dev_err_probe(dev, PTR_ERR(h->sb2), "no realtek,sb2\n");
	h->crt = syscon_regmap_lookup_by_phandle(dev->of_node, "realtek,crt");
	if (IS_ERR(h->crt))
		return dev_err_probe(dev, PTR_ERR(h->crt), "no realtek,crt\n");

	h->desc = dma_alloc_coherent(dev, EM_NR_DESC * sizeof(*h->desc),
				      &h->desc_dma, GFP_KERNEL);
	if (!h->desc)
		return -ENOMEM;

 h->bounce = dma_alloc_coherent(dev, PAGE_SIZE, &h->bounce_dma, GFP_KERNEL);
 if (!h->bounce) {
  dma_free_coherent(dev, EM_NR_DESC * sizeof(*h->desc), h->desc, h->desc_dma);
  return -ENOMEM;
 }
 ret = devm_add_action_or_reset(dev, em_release_dma, h);
 if (ret) return ret;
 if ((h->desc_dma & 15) || (h->bounce_dma & 7) ||
     em_read(h, 0x6c) != 0x5342290a || em_read(h, 0x70) != 0x00c46d41)
  return dev_err_probe(dev, -EINVAL, "Unverified eMMC controller handoff\n");
	ret = mmc_of_parse(mmc);
	if (ret)
		return ret;
	mmc->ops = &em_ops;
 mmc->f_min = 300000;
 mmc->f_max = 20000000;
 mmc->caps = MMC_CAP_NONREMOVABLE;
 mmc->caps2 = MMC_CAP2_NO_SD | MMC_CAP2_NO_SDIO | MMC_CAP2_BOOTPART_NOACC;
 mmc->ocr_avail = MMC_VDD_32_33 | MMC_VDD_33_34 | MMC_VDD_165_195;
 mmc->max_segs = 1;
 mmc->max_seg_size = PAGE_SIZE;
 mmc->max_blk_size = 512;
 mmc->max_req_size = PAGE_SIZE;
 mmc->max_blk_count = PAGE_SIZE / 512;

	regmap_read(h->crt, CRT_PLL_EMMC1, &val);
	dev_dbg(dev, "boot loader phases: TX %lu RX %lu\n",
		FIELD_GET(PLL_TX_PHASE, val), FIELD_GET(PLL_RX_PHASE, val));
	em_hw_init(h);
 if (h->failed) return -ETIMEDOUT;

	ret = devm_request_threaded_irq(dev, irq, em_irq, em_irq_thread, 0,
					dev_name(dev), h);
	if (ret)
		return ret;

	platform_set_drvdata(pdev, h);
	ret = mmc_add_host(mmc);
	if (ret)
		return ret;
	dev_info(dev, "RTD129x eMMC (DW MSHC %04x), %lu MHz PLL\n",
		 em_read(h, 0x06c) & 0xffff, h->bus_hz / 1000000);
	return 0;
}

static void em_remove(struct platform_device *pdev)
{
	struct em_host *h = platform_get_drvdata(pdev);

	mmc_remove_host(h->mmc);
	cancel_delayed_work_sync(&h->timeout);
	em_write(h, EM_INTMASK, 0);
}

static const struct of_device_id em_of_match[] = {
	{ .compatible = "bananapi,bpi-m4-emmc-test" },
	{ .compatible = "realtek,rtd1395-emmc" },
	{ }
};
MODULE_DEVICE_TABLE(of, em_of_match);

static struct platform_driver em_driver = {
	.probe = em_probe,
	.remove = em_remove,
	.driver = {
		.name = "rtd129x-emmc",
		.of_match_table = em_of_match,
		.suppress_bind_attrs = true,
		.probe_type = PROBE_PREFER_ASYNCHRONOUS,
	},
};
module_platform_driver(em_driver);

MODULE_DESCRIPTION("Realtek RTD1295/RTD1296 eMMC host");
MODULE_LICENSE("GPL");
