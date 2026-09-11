/* Recovered from the previously executed ELF: original text/data bytes,
 * decoded instructions in comments. See README.md for provenance and scope.
 * Keep addresses fixed; PC-relative instructions are intentionally encoded. */
.option norvc
.option norelax
.section .text,"ax"
.globl _start
_start:
  .org 0x0
  .4byte 0x00000b13 /* 80000000: li s6,0 */
  .org 0x4
  .4byte 0x00000297 /* 80000004: auipc t0,0x0 */
  .org 0x8
  .4byte 0x1b428293 /* 80000008: addi t0,t0,436 # 800001b8 <trap> */
  .org 0xc
  .4byte 0x30529073 /* 8000000c: csrw mtvec,t0 */
  .org 0x10
  .4byte 0xf1402bf3 /* 80000010: csrr s7,mhartid */
  .org 0x14
  .4byte 0xfff00293 /* 80000014: li t0,-1 */
  .org 0x18
  .4byte 0x3b029073 /* 80000018: csrw pmpaddr0,t0 */
  .org 0x1c
  .4byte 0x01f00293 /* 8000001c: li t0,31 */
  .org 0x20
  .4byte 0x3a029073 /* 80000020: csrw pmpcfg0,t0 */
  .org 0x24
  .4byte 0x0010029b /* 80000024: addiw t0,zero,1 */
  .org 0x28
  .4byte 0x03d29293 /* 80000028: slli t0,t0,0x3d */
  .org 0x2c
  .4byte 0x30a29073 /* 8000002c: csrw 0x30a,t0 */
  .org 0x30
  .4byte 0x30a02373 /* 80000030: csrr t1,0x30a */
  .org 0x34
  .4byte 0x00537333 /* 80000034: and t1,t1,t0 */
  .org 0x38
  .4byte 0x18030063 /* 80000038: beqz t1,800001b8 <trap> */
  .org 0x3c
  .4byte 0x00000a17 /* 8000003c: auipc s4,0x0 */
  .org 0x40
  .4byte 0x204a0a13 /* 80000040: addi s4,s4,516 # 80000240 <mailbox> */
  .org 0x44
  .4byte 0x00009497 /* 80000044: auipc s1,0x9 */
  .org 0x48
  .4byte 0xfbc48493 /* 80000048: addi s1,s1,-68 # 80009000 <leaf> */
  .org 0x4c
  .4byte 0x00848493 /* 8000004c: addi s1,s1,8 */
  .org 0x50
  .4byte 0x40001437 /* 80000050: lui s0,0x40001 */
  .org 0x54
  .4byte 0x0000a917 /* 80000054: auipc s2,0xa */
  .org 0x58
  .4byte 0xfac90913 /* 80000058: addi s2,s2,-84 # 8000a000 <target> */
  .org 0x5c
  .4byte 0x00295913 /* 8000005c: srli s2,s2,0x2 */
  .org 0x60
  .4byte 0x00796913 /* 80000060: ori s2,s2,7 */
  .org 0x64
  .4byte 0x040b9863 /* 80000064: bnez s7,800000b4 <wait_boot> */
  .org 0x68
  .4byte 0x00004397 /* 80000068: auipc t2,0x4 */
  .org 0x6c
  .4byte 0xf9838393 /* 8000006c: addi t2,t2,-104 # 80004000 <root> */
  .org 0x70
  .4byte 0x00008317 /* 80000070: auipc t1,0x8 */
  .org 0x74
  .4byte 0xf9030313 /* 80000074: addi t1,t1,-112 # 80008000 <middle> */
  .org 0x78
  .4byte 0x00235293 /* 80000078: srli t0,t1,0x2 */
  .org 0x7c
  .4byte 0x0012e293 /* 8000007c: ori t0,t0,1 */
  .org 0x80
  .4byte 0x0053b423 /* 80000080: sd t0,8(t2) */
  .org 0x84
  .4byte 0x00009297 /* 80000084: auipc t0,0x9 */
  .org 0x88
  .4byte 0xf7c28293 /* 80000088: addi t0,t0,-132 # 80009000 <leaf> */
  .org 0x8c
  .4byte 0x0022d293 /* 8000008c: srli t0,t0,0x2 */
  .org 0x90
  .4byte 0x0012e293 /* 80000090: ori t0,t0,1 */
  .org 0x94
  .4byte 0x00533023 /* 80000094: sd t0,0(t1) */
  .org 0x98
  .4byte 0x200002b7 /* 80000098: lui t0,0x20000 */
  .org 0x9c
  .4byte 0x0cf2829b /* 8000009c: addiw t0,t0,207 # 200000cf <_start-0x5fffff31> */
  .org 0xa0
  .4byte 0x0053b823 /* 800000a0: sd t0,16(t2) */
  .org 0xa4
  .4byte 0x0124b023 /* 800000a4: sd s2,0(s1) */
  .org 0xa8
  .4byte 0x00100293 /* 800000a8: li t0,1 */
  .org 0xac
  .4byte 0x0310000f /* 800000ac: fence rw,w */
  .org 0xb0
  .4byte 0x005a3023 /* 800000b0: sd t0,0(s4) */
.globl wait_boot
wait_boot:
  .org 0xb4
  .4byte 0x000a3283 /* 800000b4: ld t0,0(s4) */
  .org 0xb8
  .4byte 0xfe028ee3 /* 800000b8: beqz t0,800000b4 <wait_boot> */
  .org 0xbc
  .4byte 0x0230000f /* 800000bc: fence r,rw */
  .org 0xc0
  .4byte 0x00004297 /* 800000c0: auipc t0,0x4 */
  .org 0xc4
  .4byte 0xf4028293 /* 800000c4: addi t0,t0,-192 # 80004000 <root> */
  .org 0xc8
  .4byte 0x00c2d293 /* 800000c8: srli t0,t0,0xc */
  .org 0xcc
  .4byte 0xfff0031b /* 800000cc: addiw t1,zero,-1 */
  .org 0xd0
  .4byte 0x03f31313 /* 800000d0: slli t1,t1,0x3f */
  .org 0xd4
  .4byte 0x0062e2b3 /* 800000d4: or t0,t0,t1 */
  .org 0xd8
  .4byte 0x18029073 /* 800000d8: csrw satp,t0 */
  .org 0xdc
  .4byte 0x12000073 /* 800000dc: sfence.vma */
  .org 0xe0
  .4byte 0x00000297 /* 800000e0: auipc t0,0x0 */
  .org 0xe4
  .4byte 0x02828293 /* 800000e4: addi t0,t0,40 # 80000108 <body> */
  .org 0xe8
  .4byte 0x34129073 /* 800000e8: csrw mepc,t0 */
  .org 0xec
  .4byte 0x000022b7 /* 800000ec: lui t0,0x2 */
  .org 0xf0
  .4byte 0x8002829b /* 800000f0: addiw t0,t0,-2048 # 1800 <_start-0x7fffe800> */
  .org 0xf4
  .4byte 0x3002b073 /* 800000f4: csrc mstatus,t0 */
  .org 0xf8
  .4byte 0x000012b7 /* 800000f8: lui t0,0x1 */
  .org 0xfc
  .4byte 0x8002829b /* 800000fc: addiw t0,t0,-2048 # 800 <_start-0x7ffff800> */
  .org 0x100
  .4byte 0x3002a073 /* 80000100: csrs mstatus,t0 */
  .org 0x104
  .4byte 0x30200073 /* 80000104: mret */
.globl body
body:
  .org 0x108
  .4byte 0x060b9263 /* 80000108: bnez s7,8000016c <reader> */
.globl wait_ready
wait_ready:
  .org 0x10c
  .4byte 0x008a3283 /* 8000010c: ld t0,8(s4) */
  .org 0x110
  .4byte 0xfe028ee3 /* 80000110: beqz t0,8000010c <wait_ready> */
  .org 0x114
  .4byte 0x0230000f /* 80000114: fence r,rw */
  .org 0x118
  .4byte 0x10000293 /* 80000118: li t0,256 */
.globl writer_modify
writer_modify:
  .org 0x11c
  .4byte 0x05a00293 /* 8000011c: li t0,90 */
  .org 0x120
  .4byte 0x00543023 /* 80000120: sd t0,0(s0) # 40001000 <_start-0x3ffff000> */
.globl writer_fence
writer_fence:
  .org 0x124
  .4byte 0x12000073 /* 80000124: sfence.vma */
  .org 0x128
  .4byte 0x00100293 /* 80000128: li t0,1 */
  .org 0x12c
  .4byte 0x0310000f /* 8000012c: fence rw,w */
.globl request_publish
request_publish:
  .org 0x130
  .4byte 0x005a3823 /* 80000130: sd t0,16(s4) */
.globl wait_ack
wait_ack:
  .org 0x134
  .4byte 0x018a3283 /* 80000134: ld t0,24(s4) */
  .org 0x138
  .4byte 0xfe028ee3 /* 80000138: beqz t0,80000134 <wait_ack> */
  .org 0x13c
  .4byte 0x0230000f /* 8000013c: fence r,rw */
.globl writer_check
writer_check:
  .org 0x140
  .4byte 0x0004b983 /* 80000140: ld s3,0(s1) */
  .org 0x144
  .4byte 0x0c096913 /* 80000144: ori s2,s2,192 */
  .org 0x148
  .4byte 0x00098293 /* 80000148: mv t0,s3 */
  .org 0x14c
  .4byte 0x07229263 /* 8000014c: bne t0,s2,800001b0 <fail> */
  .org 0x150
  .4byte 0x0000a297 /* 80000150: auipc t0,0xa */
  .org 0x154
  .4byte 0xeb028293 /* 80000154: addi t0,t0,-336 # 8000a000 <target> */
  .org 0x158
  .4byte 0x0002b283 /* 80000158: ld t0,0(t0) */
  .org 0x15c
  .4byte 0x05a00313 /* 8000015c: li t1,90 */
  .org 0x160
  .4byte 0x04629863 /* 80000160: bne t0,t1,800001b0 <fail> */
  .org 0x164
  .4byte 0x00100513 /* 80000164: li a0,1 */
  .org 0x168
  .4byte 0x05c0006f /* 80000168: j 800001c4 <finish> */
.globl reader
reader:
  .org 0x16c
  .4byte 0x00000013 /* 8000016c: nop */
  .org 0x170
  .4byte 0x00100293 /* 80000170: li t0,1 */
  .org 0x174
  .4byte 0x0310000f /* 80000174: fence rw,w */
  .org 0x178
  .4byte 0x005a3423 /* 80000178: sd t0,8(s4) */
.globl wait_request
wait_request:
  .org 0x17c
  .4byte 0x010a3283 /* 8000017c: ld t0,16(s4) */
  .org 0x180
  .4byte 0xfe028ee3 /* 80000180: beqz t0,8000017c <wait_request> */
  .org 0x184
  .4byte 0x0230000f /* 80000184: fence r,rw */
  .org 0x188
  .4byte 0x05a00293 /* 80000188: li t0,90 */
.globl reader_store
reader_store:
  .org 0x18c
  .4byte 0x00043303 /* 8000018c: ld t1,0(s0) */
  .org 0x190
  .4byte 0x05a00393 /* 80000190: li t2,90 */
  .org 0x194
  .4byte 0x00731e63 /* 80000194: bne t1,t2,800001b0 <fail> */
.globl reader_fence
reader_fence:
  .org 0x198
  .4byte 0x12000073 /* 80000198: sfence.vma */
  .org 0x19c
  .4byte 0x00100293 /* 8000019c: li t0,1 */
  .org 0x1a0
  .4byte 0x0310000f /* 800001a0: fence rw,w */
.globl ack_publish
ack_publish:
  .org 0x1a4
  .4byte 0x005a3c23 /* 800001a4: sd t0,24(s4) */
.globl park
park:
  .org 0x1a8
  .4byte 0x10500073 /* 800001a8: wfi */
  .org 0x1ac
  .4byte 0xffdff06f /* 800001ac: j 800001a8 <park> */
.globl fail
fail:
  .org 0x1b0
  .4byte 0x00300513 /* 800001b0: li a0,3 */
  .org 0x1b4
  .4byte 0x0100006f /* 800001b4: j 800001c4 <finish> */
.globl trap
trap:
  .org 0x1b8
  .4byte 0x34202c73 /* 800001b8: csrr s8,mcause */
  .org 0x1bc
  .4byte 0x34102cf3 /* 800001bc: csrr s9,mepc */
  .org 0x1c0
  .4byte 0x00b00513 /* 800001c0: li a0,11 */
.globl finish
finish:
  .org 0x1c4
  .4byte 0x00000297 /* 800001c4: auipc t0,0x0 */
  .org 0x1c8
  .4byte 0x03c28293 /* 800001c8: addi t0,t0,60 # 80000200 <tohost> */
  .org 0x1cc
  .4byte 0x00a2b023 /* 800001cc: sd a0,0(t0) */
  .org 0x1d0
  .4byte 0x0000006f /* 800001d0: j 800001d0 <finish+0xc> */

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
