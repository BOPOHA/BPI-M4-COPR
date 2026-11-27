/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef BPI_M4_SD_WRITE_POLICY_H
#define BPI_M4_SD_WRITE_POLICY_H

/* SDHC sector addressing; subtraction avoids wrapping the range end. */
static inline int sd_write_range_valid(unsigned long long start,
		unsigned long long count)
{
	return start && count && start <= 0xffffffffULL &&
		count <= 0x100000000ULL - start;
}

static inline int sd_write_in_range(unsigned long long start,
		unsigned long long count, unsigned int sector, unsigned int blocks)
{
	return sd_write_range_valid(start, count) && blocks &&
		sector >= start && sector - start < count &&
		blocks <= count - (sector - start);
}

/* Only R1 without errors, READY_FOR_DATA and TRAN confirms programming. */
static inline int sd_write_status_error(unsigned int status)
{
	/* R1_STATUS plus CARD_IS_LOCKED, which R1_STATUS itself omits. */
	return !!(status & 0xfff9a000U) || !!(status & (1U << 25));
}

static inline int sd_write_status_ready(unsigned int status)
{
	return !sd_write_status_error(status) && (status & (1U << 8)) &&
		((status >> 9) & 15) == 4;
}
#endif
