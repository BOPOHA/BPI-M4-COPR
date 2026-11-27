"""Run the actual native-write command path against a fault-injecting controller."""
from pathlib import Path
import struct
import hashlib
import io
import json
from contextlib import redirect_stdout
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include "write-policy.h"
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#define PAGE_SIZE 4096
#define SD_BUFFER_BYTES PAGE_SIZE
#define GFP_KERNEL 0
#define MMC_DATA_WRITE 256
#define MMC_DATA_READ 512
#define MMC_WRITE_BLOCK 24
#define MMC_WRITE_MULTIPLE_BLOCK 25
#define MMC_STOP_TRANSMISSION 12
#define MMC_SEND_STATUS 13
#define MMC_RSP_PRESENT 1
#define MMC_RSP_136 2
#define MMC_RSP_CRC 4
#define MMC_RSP_BUSY 8
#define MMC_RSP_R1 (MMC_RSP_PRESENT | MMC_RSP_CRC)
#define MMC_RSP_R1B (MMC_RSP_R1 | MMC_RSP_BUSY)
#define MMC_CMD_AC 0
#define MMC_CMD_ADTC 32
#define READ_ONCE(x) (x)
#define kmalloc(n, f) malloc(n)
#define kfree(p) free(p)
#define dev_info(...) ((void)0)
#define dev_err(...) ((void)0)
#define dma_wmb() ((void)0)
#define dma_rmb() ((void)0)
#define mb() ((void)0)
#define __module_get(x) ((void)0)
#define container_of(p,t,m) ((t *)((char *)(p) - offsetof(t,m)))
REGISTERS
METRICS
struct scatterlist { void *ptr; unsigned int len; };
struct mmc_data { unsigned int blksz, blocks, flags, sg_len, bytes_xfered; struct scatterlist *sg; int error; };
struct mmc_command { unsigned int opcode, arg, flags, resp[4], retries; struct mmc_data *data; int error; };
struct mmc_request { struct mmc_command *cmd, *stop, *sbc; struct mmc_data *data; };
struct mmc_card { unsigned int raw_cid[4], rca; bool blockaddr; struct { unsigned int capacity; } csd; };
struct mmc_host { struct mmc_card *card; };
struct work_struct { int unused; };
struct sd_probe {
    struct mmc_host *mmc; unsigned char *regs, *bridge; void *buffer;
    unsigned long dma; unsigned int data_clock; bool failed;
    struct work_struct work; struct mmc_request *mrq;
};
static bool write_enable=true, native_write=true;
static unsigned long long scratch_start=100, scratch_sectors=8;
static char *scratch_cid="413432534433324730002a677401128b";
static unsigned long jiffies;
#define msecs_to_jiffies(x) (x)
#define time_before(a,b) ((a)<(b))
static void usleep_range(unsigned int a, unsigned int b) { (void)a; (void)b; jiffies+=1000; }
static unsigned char regs[512], buffer[PAGE_SIZE], media[PAGE_SIZE];
static unsigned int sequence[32], calls, state=4, polls, program_polls, done_calls;
static int scenario;
static struct mmc_data *active_data;
static u64 sd_now(void) { return 1; }
static void sd_count(struct sd_probe *h, enum sd_metric m, u64 v) { (void)h; (void)m; (void)v; }
static void sd_elapsed(struct sd_probe *h, enum sd_metric m, u64 s) { (void)h; (void)m; (void)s; }
static unsigned int sd_poll_us(void) { return 100; }
static bool mmc_card_is_blockaddr(struct mmc_card *c) { return c->blockaddr; }
static void sg_init_one(struct scatterlist *sg, void *p, unsigned int n) { sg->ptr=p; sg->len=n; }
static unsigned int sg_copy_to_buffer(struct scatterlist *sg, unsigned int count, void *p, unsigned int n) {
    if (!count || sg->len < n) return 0;
    memcpy(p,sg->ptr,n); return n;
}
static unsigned int sg_copy_from_buffer(struct scatterlist *sg, unsigned int count, const void *p, unsigned int n) {
    if (!count || sg->len < n) return 0;
    memcpy(sg->ptr,p,n); return n;
}
static u32 get_unaligned_be32(const void *p) {
    const u8 *b=p; return ((u32)b[0]<<24) | ((u32)b[1]<<16) | ((u32)b[2]<<8) | b[3];
}
static u8 readb(const void *p) { return *(const u8 *)p; }
static u32 readl(const void *p) { u32 v; memcpy(&v,p,4); return v; }
static void writel(u32 v, void *p) { memcpy(p,&v,4); }
static void response(u32 v) { for (unsigned int i=0;i<4;i++) regs[CMD0+1+i]=v>>(24-8*i); }
static void writeb(u8 v, void *p) {
    *(u8 *)p=v;
    if (p != regs+TRANS || !(v&0x80)) return;
    unsigned int op=regs[CMD0]&63;
    assert(calls<32); sequence[calls++]=op;
    if (native_write) assert(active_data->bytes_xfered==0); /* no premature burst acknowledgement */
    regs[TRANS]=0x60; regs[ST1]=regs[ST2]=0;
    if (op==25) {
        assert(state==4 && v==0x89 && regs[CFG2]==1 && regs[CFG3]==0);
        assert(readl(regs+DMA3)==1 && readl(regs+DMA2)==active_data->blocks);
        assert(regs[BYTELO]==0 && regs[BYTEHI]==2);
        assert(regs[BLOCKLO]==active_data->blocks && regs[BLOCKHI]==0);
        assert(readl(regs+DMA1)==0x100000>>3);
        assert(!memcmp(buffer,active_data->sg->ptr,active_data->blocks*512));
        memcpy(media,buffer,active_data->blocks*512); state=(scenario==30 || scenario==32) ? 4 : 6;
        /* AUTO_WRITE1 CMD registers are not an R1 response. */
        response(0xffffffff);
        if (scenario==10) regs[TRANS]=0;
        if (scenario==11) regs[TRANS]=0x10;
        if (scenario==12) regs[ST2]=1;
        if (scenario==14) regs[ST1]=0x20;
        if (scenario==15) regs[ST1]=0x02;
        if (scenario!=13) writel(0,regs+DMA3);
    } else if (op==24) {
        assert(!native_write && state==4 && v==0x8a && regs[CFG2]==1);
        assert(readl(regs+DMA3)==1 && readl(regs+DMA2)==1);
        u32 arg=get_unaligned_be32(regs+CMD0+1);
        assert(arg>=100 && arg<108);
        memcpy(media+(arg-100)*512,buffer,512); state=7;
        response(0); writel(0,regs+DMA3);
    } else if (op==12) {
        assert(state==6 && regs[CFG2]==0x7c && regs[CFG3]==0 && v==0x88);
        assert(!(readl(regs+DMA3)&1)); /* stop only after DMA is released */
        state=7; response(0);
        if (scenario==16) regs[TRANS]=0;
        if (scenario==17) response(1U<<31);
    } else if (op==13) {
        polls++;
        if (native_write) assert(regs[CFG3]==0); /* BSP CMD13 preserves stream config */
        if (state==6) { assert(polls==1); response(6<<9); }
        else if (state==4) {
            response((4<<9)|256);
            if (scenario==32 && polls==1) response(4<<9);
        } else {
            program_polls++;
            if (scenario==18 || program_polls==1) response(7<<9);
            else { state=4; response((4<<9)|256); }
        }
        if (scenario==19) response((4<<9)|256|(1U<<25));
        if (scenario==20) regs[TRANS]=0;
        if (scenario==31) response(0x00400900); /* actual hardware ILLEGAL_COMMAND */
        if (scenario==33) response(0); /* unexpected IDLE state */
    } else abort();
}
#define read_poll_timeout(fn,val,cond,delay,timeout,sleep,...) \
    ((void)(delay),(void)(timeout),(void)(sleep),(val)=fn(__VA_ARGS__),(cond)?0:-ETIMEDOUT)
#define readl_poll_timeout(addr,val,cond,delay,timeout) \
    ((void)(delay),(void)(timeout),(val)=readl(addr),(cond)?0:-ETIMEDOUT)
static void mmc_request_done(struct mmc_host *h, struct mmc_request *r) { (void)h; (void)r; done_calls++; }
ACTUAL
int main(int argc, char **argv) {
    assert(argc==2); scenario=atoi(argv[1]);
    struct mmc_card card={ .raw_cid={0x41343253,0x44333247,0x30002a67,0x7401128b}, .blockaddr=true,.rca=1,.csd={108} };
    struct mmc_host mmc={.card=&card};
    struct sd_probe host={.mmc=&mmc,.regs=regs,.bridge=regs+SYNC,.buffer=buffer,.dma=0x100000,.data_clock=0x2100};
    unsigned char input[PAGE_SIZE];
    for (unsigned int i=0;i<PAGE_SIZE;i++) input[i]=(i*31+7)%251;
    struct scatterlist sg={.ptr=input,.len=PAGE_SIZE};
    struct mmc_data data={.blksz=512,.blocks=8,.flags=MMC_DATA_WRITE,.sg=&sg,.sg_len=1,.bytes_xfered=123};
    struct mmc_command cmd={.opcode=25,.arg=100,.flags=MMC_RSP_R1|MMC_CMD_ADTC,.data=&data,.retries=5};
    struct mmc_command stop={.opcode=12}, sbc={.opcode=23};
    struct mmc_request mrq={.cmd=&cmd,.data=&data,.stop=&stop};
    active_data=&data;
    switch (scenario) {
    case 0: break;
    case 1: cmd.arg=101; break;
    case 2: card.raw_cid[0]++; break;
    case 3: write_enable=false; break;
    case 4: data.blocks=9; break;
    case 5: data.blocks=0; break;
    case 6: data.flags|=MMC_DATA_READ; break;
    case 7: card.blockaddr=false; break;
    case 8: mmc.card=NULL; break;
    case 9: sg.len=4095; break;
    case 10: case 11: case 12: case 13: case 14: case 15:
    case 16: case 17: case 18: case 19: case 20: break;
    case 21: card.csd.capacity=107; break;
    case 22: mrq.stop=NULL; break;
    case 23: data.blocks=2; break;
    case 24: data.blksz=1024; break;
    case 25: mrq.sbc=&sbc; break;
    case 26: cmd.data=NULL; break;
    case 27: data.blocks=1; break;
    case 28: host.failed=true; break;
    case 29: native_write=false; break;
    case 30: case 31: case 32: case 33: break;
    default: abort();
    }
    host.mrq=&mrq; sd_work(&host.work);
    assert(done_calls==1 && !host.mrq && cmd.retries==0);
    bool success=scenario==0 || scenario==17 || scenario==22 || scenario==23 || scenario==27 || scenario==30 || scenario==32;
    if (scenario==29) {
        assert(!cmd.error && !data.error && !stop.error && data.bytes_xfered==4096);
        assert(!memcmp(input,media,4096) && calls==17 && polls==9);
        for (unsigned int i=0;i<calls;i++) assert(sequence[i]==24 || sequence[i]==13);
    } else if (success) {
        assert(!cmd.error && !data.error && (!mrq.stop || !stop.error));
        assert(data.bytes_xfered==data.blocks*512);
        if (scenario==30 || scenario==32) {
            assert(calls==(scenario==30 ? 2 : 3));
            for (unsigned int i=1;i<calls;i++) assert(sequence[i]==13);
        } else {
            assert(calls==5 && polls==3);
            assert(sequence[0]==25 && sequence[1]==13 && sequence[2]==12 && sequence[3]==13 && sequence[4]==13);
        }
        assert(!memcmp(input,media,data.bytes_xfered));
        assert(sd_write_status_ready(cmd.resp[0]) && !host.failed);
    } else {
        assert(cmd.error && data.error && data.bytes_xfered==0);
        if ((scenario>=10 && scenario<=20) || scenario==31 || scenario==33) {
            assert(host.failed);
            if (scenario<=15) assert(calls==1 && !polls && stop.error==-ECANCELED);
            if (scenario==16) assert(calls==3 && polls==1 && stop.error);
            if (scenario==19 || scenario==20 || scenario==31 || scenario==33) assert(calls==2 && stop.error==-ECANCELED);
            unsigned int previous=calls; u8 snapshot[PAGE_SIZE]; memcpy(snapshot,buffer,PAGE_SIZE);
            /* A second request cannot clear/reuse the DMA buffer after freezing. */
            host.mrq=&mrq; sd_work(&host.work);
            assert(calls==previous && !memcmp(snapshot,buffer,PAGE_SIZE) && !data.bytes_xfered);
        } else assert(!calls);
    }
    if (scenario==25) assert(sbc.error==-EOPNOTSUPP && stop.error==-ECANCELED);
    return 0;
}
'''


