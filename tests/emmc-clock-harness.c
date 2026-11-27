/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>

typedef uint32_t u32;
#define BIT(n) (1U << (n))
struct em_host {
	void *crt, *dev;
	unsigned long bus_hz;
};
static u32 pll, control, output, ckgen;
static unsigned int reads, fail_read;

static int regmap_read(void *map, unsigned int reg, u32 *value)
{
	(void)map;
	if (++reads == fail_read)
		return -EIO;
	switch (reg) {
	case 0x1f8: *value = pll; break;
	case 0x1f0: *value = control; break;
	case 0x1fc: *value = output; break;
	default: assert(0);
	}
	return 0;
}

static u32 em_read(struct em_host *host, unsigned int reg)
{
	(void)host;
	assert(reg == 0x478);
	return ckgen;
}

#define dev_info(...) ((void)0)
#define dev_err_probe(device, error, ...) (error)
#include "emmc-clock-function.h"

static void reset(u32 frequency)
{
	pll = frequency;
	control = 3;
	output = 7;
	ckgen = 0x2100;
	reads = fail_read = 0;
}

static void rejected(void)
{
	struct em_host host = { .bus_hz = 123 };

	assert(em_inherited_clock(&host) == -EINVAL);
	assert(host.bus_hz == 123);
}

int main(void)
{
	static const struct {
		u32 pll;
		unsigned long hz;
	} rates[] = {
		{ 0x00464388, 80000000 },
		{ 0x00574388, 100000000 },
		{ 0x00a64388, 200000000 },
	};
	for (unsigned int i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
		struct em_host host = { 0 };

		reset(rates[i].pll);
		assert(em_inherited_clock(&host) == 0);
		assert(host.bus_hz == rates[i].hz);
		assert(reads == 3);
	}
	reset(0x00474388); rejected(); /* unknown frequency */
	reset(0x00464389); rejected(); /* unverified analog settings */
	reset(0x00464388); control = 1; rejected(); /* PLL held in reset */
	reset(0x00464388); output = 6; rejected(); /* output disabled */
	reset(0x00464388); ckgen = 0x2010; rejected(); /* wrapper divider */
	reset(0x00464388); ckgen = 0x72100; rejected(); /* alternate clock */
	for (unsigned int i = 1; i <= 3; i++) {
		struct em_host host = { .bus_hz = 123 };

		reset(0x00464388);
		fail_read = i;
		assert(em_inherited_clock(&host) == -EIO);
		assert(host.bus_hz == 123);
		assert(reads == i);
	}
	puts("eMMC clock guard: known rates and rejected handoffs passed");
	return 0;
}
