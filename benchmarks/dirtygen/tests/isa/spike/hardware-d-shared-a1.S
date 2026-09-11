/* Recovered from the previously executed ELF: original text/data bytes,
 * decoded instructions in comments. See README.md for provenance and scope.
 * Keep addresses fixed; PC-relative instructions are intentionally encoded. */
.option norvc
.option norelax
.section .text,"ax"
.globl _start
_start:
  .org 0x0
  .4byte 0x00000297 /* 80000000: auipc t0,0x0 */
  .org 0x4
  .4byte 0x1bc28293 /* 80000004: addi t0,t0,444 # 800001bc <trap> */
  .org 0x8
  .4byte 0x30529073 /* 80000008: csrw mtvec,t0 */
  .org 0xc
  .4byte 0xf1402bf3 /* 8000000c: csrr s7,mhartid */
  .org 0x10
  .4byte 0xfff00293 /* 80000010: li t0,-1 */
  .org 0x14
  .4byte 0x3b029073 /* 80000014: csrw pmpaddr0,t0 */
  .org 0x18
  .4byte 0x01f00293 /* 80000018: li t0,31 */
  .org 0x1c
  .4byte 0x3a029073 /* 8000001c: csrw pmpcfg0,t0 */
  .org 0x20
  .4byte 0x0010029b /* 80000020: addiw t0,zero,1 */
  .org 0x24
  .4byte 0x03d29293 /* 80000024: slli t0,t0,0x3d */
  .org 0x28
  .4byte 0x30a29073 /* 80000028: csrw 0x30a,t0 */
  .org 0x2c
  .4byte 0x30a02373 /* 8000002c: csrr t1,0x30a */
  .org 0x30
  .4byte 0x00537333 /* 80000030: and t1,t1,t0 */
  .org 0x34
  .4byte 0x18030463 /* 80000034: beqz t1,800001bc <trap> */
  .org 0x38
  .4byte 0x00000a17 /* 80000038: auipc s4,0x0 */
  .org 0x3c
  .4byte 0x208a0a13 /* 8000003c: addi s4,s4,520 # 80000240 <mailbox> */
  .org 0x40
  .4byte 0x00009497 /* 80000040: auipc s1,0x9 */
  .org 0x44
  .4byte 0xfc048493 /* 80000044: addi s1,s1,-64 # 80009000 <leaf> */
  .org 0x48
  .4byte 0x00848493 /* 80000048: addi s1,s1,8 */
  .org 0x4c
  .4byte 0x40001437 /* 8000004c: lui s0,0x40001 */
  .org 0x50
  .4byte 0x0000a917 /* 80000050: auipc s2,0xa */
  .org 0x54
  .4byte 0xfb090913 /* 80000054: addi s2,s2,-80 # 8000a000 <target> */
  .org 0x58
  .4byte 0x00295913 /* 80000058: srli s2,s2,0x2 */
  .org 0x5c
  .4byte 0x04796913 /* 8000005c: ori s2,s2,71 */
  .org 0x60
  .4byte 0x040b9863 /* 80000060: bnez s7,800000b0 <wait_boot> */
  .org 0x64
  .4byte 0x00004397 /* 80000064: auipc t2,0x4 */
  .org 0x68
  .4byte 0xf9c38393 /* 80000068: addi t2,t2,-100 # 80004000 <root> */
  .org 0x6c
  .4byte 0x00008317 /* 8000006c: auipc t1,0x8 */
  .org 0x70
  .4byte 0xf9430313 /* 80000070: addi t1,t1,-108 # 80008000 <middle> */
  .org 0x74
  .4byte 0x00235293 /* 80000074: srli t0,t1,0x2 */
  .org 0x78
  .4byte 0x0012e293 /* 80000078: ori t0,t0,1 */
  .org 0x7c
  .4byte 0x0053b423 /* 8000007c: sd t0,8(t2) */
  .org 0x80
  .4byte 0x00009297 /* 80000080: auipc t0,0x9 */
  .org 0x84
  .4byte 0xf8028293 /* 80000084: addi t0,t0,-128 # 80009000 <leaf> */
  .org 0x88
  .4byte 0x0022d293 /* 80000088: srli t0,t0,0x2 */
  .org 0x8c
  .4byte 0x0012e293 /* 8000008c: ori t0,t0,1 */
  .org 0x90
  .4byte 0x00533023 /* 80000090: sd t0,0(t1) */
  .org 0x94
  .4byte 0x200002b7 /* 80000094: lui t0,0x20000 */
  .org 0x98
  .4byte 0x0cf2829b /* 80000098: addiw t0,t0,207 # 200000cf <_start-0x5fffff31> */
  .org 0x9c
  .4byte 0x0053b823 /* 8000009c: sd t0,16(t2) */
  .org 0xa0
  .4byte 0x0124b023 /* 800000a0: sd s2,0(s1) */
  .org 0xa4
  .4byte 0x00100293 /* 800000a4: li t0,1 */
  .org 0xa8
  .4byte 0x0310000f /* 800000a8: fence rw,w */
  .org 0xac
  .4byte 0x005a3023 /* 800000ac: sd t0,0(s4) */
.globl wait_boot
wait_boot:
  .org 0xb0
  .4byte 0x000a3283 /* 800000b0: ld t0,0(s4) */
  .org 0xb4
  .4byte 0xfe028ee3 /* 800000b4: beqz t0,800000b0 <wait_boot> */
  .org 0xb8
  .4byte 0x0230000f /* 800000b8: fence r,rw */
  .org 0xbc
  .4byte 0x00004297 /* 800000bc: auipc t0,0x4 */
  .org 0xc0
  .4byte 0xf4428293 /* 800000c0: addi t0,t0,-188 # 80004000 <root> */
  .org 0xc4
  .4byte 0x00c2d293 /* 800000c4: srli t0,t0,0xc */
  .org 0xc8
  .4byte 0xfff0031b /* 800000c8: addiw t1,zero,-1 */
  .org 0xcc
  .4byte 0x03f31313 /* 800000cc: slli t1,t1,0x3f */
  .org 0xd0
  .4byte 0x0062e2b3 /* 800000d0: or t0,t0,t1 */
  .org 0xd4
  .4byte 0x18029073 /* 800000d4: csrw satp,t0 */
  .org 0xd8
  .4byte 0x12000073 /* 800000d8: sfence.vma */
  .org 0xdc
  .4byte 0x00000297 /* 800000dc: auipc t0,0x0 */
  .org 0xe0
  .4byte 0x02828293 /* 800000e0: addi t0,t0,40 # 80000104 <body> */
  .org 0xe4
  .4byte 0x34129073 /* 800000e4: csrw mepc,t0 */
  .org 0xe8
  .4byte 0x000022b7 /* 800000e8: lui t0,0x2 */
  .org 0xec
  .4byte 0x8002829b /* 800000ec: addiw t0,t0,-2048 # 1800 <_start-0x7fffe800> */
  .org 0xf0
  .4byte 0x3002b073 /* 800000f0: csrc mstatus,t0 */
  .org 0xf4
  .4byte 0x000012b7 /* 800000f4: lui t0,0x1 */
  .org 0xf8
  .4byte 0x8002829b /* 800000f8: addiw t0,t0,-2048 # 800 <_start-0x7ffff800> */
  .org 0xfc
  .4byte 0x3002a073 /* 800000fc: csrs mstatus,t0 */
  .org 0x100
  .4byte 0x30200073 /* 80000100: mret */
.globl body
body:
  .org 0x104
  .4byte 0x060b9263 /* 80000104: bnez s7,80000168 <reader> */
.globl wait_ready
wait_ready:
  .org 0x108
  .4byte 0x008a3283 /* 80000108: ld t0,8(s4) */
  .org 0x10c
  .4byte 0xfe028ee3 /* 8000010c: beqz t0,80000108 <wait_ready> */
  .org 0x110
  .4byte 0x0230000f /* 80000110: fence r,rw */
  .org 0x114
  .4byte 0x10000293 /* 80000114: li t0,256 */
.globl writer_modify
writer_modify:
  .org 0x118
  .4byte 0x05a00293 /* 80000118: li t0,90 */
  .org 0x11c
  .4byte 0x00543023 /* 8000011c: sd t0,0(s0) # 40001000 <_start-0x3ffff000> */
.globl writer_fence
writer_fence:
  .org 0x120
  .4byte 0x12000073 /* 80000120: sfence.vma */
  .org 0x124
  .4byte 0x00100293 /* 80000124: li t0,1 */
  .org 0x128
  .4byte 0x0310000f /* 80000128: fence rw,w */
.globl request_publish
request_publish:
  .org 0x12c
  .4byte 0x005a3823 /* 8000012c: sd t0,16(s4) */
.globl wait_ack
wait_ack:
  .org 0x130
  .4byte 0x018a3283 /* 80000130: ld t0,24(s4) */
  .org 0x134
  .4byte 0xfe028ee3 /* 80000134: beqz t0,80000130 <wait_ack> */
  .org 0x138
  .4byte 0x0230000f /* 80000138: fence r,rw */
.globl writer_check
writer_check:
  .org 0x13c
  .4byte 0x0004b983 /* 8000013c: ld s3,0(s1) */
  .org 0x140
  .4byte 0x0c096913 /* 80000140: ori s2,s2,192 */
  .org 0x144
  .4byte 0x00098293 /* 80000144: mv t0,s3 */
  .org 0x148
  .4byte 0x07229663 /* 80000148: bne t0,s2,800001b4 <fail> */
  .org 0x14c
  .4byte 0x0000a297 /* 8000014c: auipc t0,0xa */
  .org 0x150
  .4byte 0xeb428293 /* 80000150: addi t0,t0,-332 # 8000a000 <target> */
  .org 0x154
  .4byte 0x0002b283 /* 80000154: ld t0,0(t0) */
  .org 0x158
  .4byte 0x05a00313 /* 80000158: li t1,90 */
  .org 0x15c
  .4byte 0x04629c63 /* 8000015c: bne t0,t1,800001b4 <fail> */
  .org 0x160
  .4byte 0x00100513 /* 80000160: li a0,1 */
  .org 0x164
  .4byte 0x0640006f /* 80000164: j 800001c8 <finish> */
.globl reader
reader:
  .org 0x168
  .4byte 0x00043283 /* 80000168: ld t0,0(s0) */
  .org 0x16c
  .4byte 0x00100293 /* 8000016c: li t0,1 */
  .org 0x170
  .4byte 0x0310000f /* 80000170: fence rw,w */
  .org 0x174
  .4byte 0x005a3423 /* 80000174: sd t0,8(s4) */
.globl wait_request
wait_request:
  .org 0x178
  .4byte 0x010a3283 /* 80000178: ld t0,16(s4) */
  .org 0x17c
  .4byte 0xfe028ee3 /* 8000017c: beqz t0,80000178 <wait_request> */
  .org 0x180
  .4byte 0x0230000f /* 80000180: fence r,rw */
  .org 0x184
  .4byte 0x05a00293 /* 80000184: li t0,90 */
.globl reader_store
reader_store:
  .org 0x188
  .4byte 0x0004b303 /* 80000188: ld t1,0(s1) */
  .org 0x18c
  .4byte 0x0c037313 /* 8000018c: andi t1,t1,192 */
  .org 0x190
  .4byte 0x0c000393 /* 80000190: li t2,192 */
  .org 0x194
  .4byte 0x02731063 /* 80000194: bne t1,t2,800001b4 <fail> */
  .org 0x198
  .4byte 0x00543023 /* 80000198: sd t0,0(s0) */
.globl reader_fence
reader_fence:
  .org 0x19c
  .4byte 0x12000073 /* 8000019c: sfence.vma */
  .org 0x1a0
  .4byte 0x00100293 /* 800001a0: li t0,1 */
  .org 0x1a4
  .4byte 0x0310000f /* 800001a4: fence rw,w */
.globl ack_publish
ack_publish:
  .org 0x1a8
  .4byte 0x005a3c23 /* 800001a8: sd t0,24(s4) */
.globl park
park:
  .org 0x1ac
  .4byte 0x10500073 /* 800001ac: wfi */
  .org 0x1b0
  .4byte 0xffdff06f /* 800001b0: j 800001ac <park> */
.globl fail
fail:
  .org 0x1b4
  .4byte 0x00300513 /* 800001b4: li a0,3 */
  .org 0x1b8
  .4byte 0x0100006f /* 800001b8: j 800001c8 <finish> */
.globl trap
trap:
  .org 0x1bc
  .4byte 0x34202c73 /* 800001bc: csrr s8,mcause */
  .org 0x1c0
  .4byte 0x34102cf3 /* 800001c0: csrr s9,mepc */
  .org 0x1c4
  .4byte 0x00b00513 /* 800001c4: li a0,11 */
.globl finish
finish:
  .org 0x1c8
  .4byte 0x00000297 /* 800001c8: auipc t0,0x0 */
  .org 0x1cc
  .4byte 0x03828293 /* 800001cc: addi t0,t0,56 # 80000200 <tohost> */
  .org 0x1d0
  .4byte 0x00a2b023 /* 800001d0: sd a0,0(t0) */
  .org 0x1d4
  .4byte 0x0000006f /* 800001d4: j 800001d4 <finish+0xc> */

.section .tohost,"aw"
.globl tohost
tohost:
  .zero 8
.globl fromhost
fromhost:
  .zero 56
.globl mailbox
mailbox:
  .zero 32

.section .data,"aw"
.globl root
root:
  .zero 16384
.globl middle
middle:
  .zero 4096
.globl leaf
leaf:
  .zero 4096
.globl target
target:
  .zero 4096
