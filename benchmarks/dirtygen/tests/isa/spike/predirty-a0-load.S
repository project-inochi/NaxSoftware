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
  .4byte 0x12828293 /* 80000004: addi t0,t0,296 # 80000128 <trap> */
  .org 0x8
  .4byte 0x30529073 /* 80000008: csrw mtvec,t0 */
  .org 0xc
  .4byte 0xfff00293 /* 8000000c: li t0,-1 */
  .org 0x10
  .4byte 0x3b029073 /* 80000010: csrw pmpaddr0,t0 */
  .org 0x14
  .4byte 0x01f00293 /* 80000014: li t0,31 */
  .org 0x18
  .4byte 0x3a029073 /* 80000018: csrw pmpcfg0,t0 */
  .org 0x1c
  .4byte 0x0010029b /* 8000001c: addiw t0,zero,1 */
  .org 0x20
  .4byte 0x03d29293 /* 80000020: slli t0,t0,0x3d */
  .org 0x24
  .4byte 0x30a29073 /* 80000024: csrw 0x30a,t0 */
  .org 0x28
  .4byte 0x30a02373 /* 80000028: csrr t1,0x30a */
  .org 0x2c
  .4byte 0x00537333 /* 8000002c: and t1,t1,t0 */
  .org 0x30
  .4byte 0x0e030463 /* 80000030: beqz t1,80000118 <setup_fail> */
  .org 0x34
  .4byte 0x00004397 /* 80000034: auipc t2,0x4 */
  .org 0x38
  .4byte 0xfcc38393 /* 80000038: addi t2,t2,-52 # 80004000 <root> */
  .org 0x3c
  .4byte 0x00009297 /* 8000003c: auipc t0,0x9 */
  .org 0x40
  .4byte 0xfc428293 /* 80000040: addi t0,t0,-60 # 80009000 <leaf> */
  .org 0x44
  .4byte 0x0022d293 /* 80000044: srli t0,t0,0x2 */
  .org 0x48
  .4byte 0x0012e293 /* 80000048: ori t0,t0,1 */
  .org 0x4c
  .4byte 0x00008317 /* 8000004c: auipc t1,0x8 */
  .org 0x50
  .4byte 0xfb430313 /* 80000050: addi t1,t1,-76 # 80008000 <middle> */
  .org 0x54
  .4byte 0x00533023 /* 80000054: sd t0,0(t1) */
  .org 0x58
  .4byte 0x00235293 /* 80000058: srli t0,t1,0x2 */
  .org 0x5c
  .4byte 0x0012e293 /* 8000005c: ori t0,t0,1 */
  .org 0x60
  .4byte 0x00800313 /* 80000060: li t1,8 */
  .org 0x64
  .4byte 0x00638333 /* 80000064: add t1,t2,t1 */
  .org 0x68
  .4byte 0x00533023 /* 80000068: sd t0,0(t1) */
  .org 0x6c
  .4byte 0x200002b7 /* 8000006c: lui t0,0x20000 */
  .org 0x70
  .4byte 0x0cf2829b /* 80000070: addiw t0,t0,207 # 200000cf <_start-0x5fffff31> */
  .org 0x74
  .4byte 0x01000313 /* 80000074: li t1,16 */
  .org 0x78
  .4byte 0x00638333 /* 80000078: add t1,t2,t1 */
  .org 0x7c
  .4byte 0x00533023 /* 8000007c: sd t0,0(t1) */
  .org 0x80
  .4byte 0x00009497 /* 80000080: auipc s1,0x9 */
  .org 0x84
  .4byte 0xf8048493 /* 80000084: addi s1,s1,-128 # 80009000 <leaf> */
  .org 0x88
  .4byte 0x00848493 /* 80000088: addi s1,s1,8 */
  .org 0x8c
  .4byte 0x0000a917 /* 8000008c: auipc s2,0xa */
  .org 0x90
  .4byte 0xf7490913 /* 80000090: addi s2,s2,-140 # 8000a000 <target> */
  .org 0x94
  .4byte 0x00295913 /* 80000094: srli s2,s2,0x2 */
  .org 0x98
  .4byte 0x00796913 /* 80000098: ori s2,s2,7 */
  .org 0x9c
  .4byte 0x08096913 /* 8000009c: ori s2,s2,128 */
  .org 0xa0
  .4byte 0x0124b023 /* 800000a0: sd s2,0(s1) */
  .org 0xa4
  .4byte 0x40001437 /* 800000a4: lui s0,0x40001 */
  .org 0xa8
  .4byte 0x00c3d293 /* 800000a8: srli t0,t2,0xc */
  .org 0xac
  .4byte 0xfff0031b /* 800000ac: addiw t1,zero,-1 */
  .org 0xb0
  .4byte 0x03f31313 /* 800000b0: slli t1,t1,0x3f */
  .org 0xb4
  .4byte 0x0062e2b3 /* 800000b4: or t0,t0,t1 */
  .org 0xb8
  .4byte 0x18029073 /* 800000b8: csrw satp,t0 */
  .org 0xbc
  .4byte 0x12000073 /* 800000bc: sfence.vma */
  .org 0xc0
  .4byte 0x00000297 /* 800000c0: auipc t0,0x0 */
  .org 0xc4
  .4byte 0x02828293 /* 800000c4: addi t0,t0,40 # 800000e8 <body> */
  .org 0xc8
  .4byte 0x34129073 /* 800000c8: csrw mepc,t0 */
  .org 0xcc
  .4byte 0x000022b7 /* 800000cc: lui t0,0x2 */
  .org 0xd0
  .4byte 0x8002829b /* 800000d0: addiw t0,t0,-2048 # 1800 <_start-0x7fffe800> */
  .org 0xd4
  .4byte 0x3002b073 /* 800000d4: csrc mstatus,t0 */
  .org 0xd8
  .4byte 0x000012b7 /* 800000d8: lui t0,0x1 */
  .org 0xdc
  .4byte 0x8002829b /* 800000dc: addiw t0,t0,-2048 # 800 <_start-0x7ffff800> */
  .org 0xe0
  .4byte 0x3002a073 /* 800000e0: csrs mstatus,t0 */
  .org 0xe4
  .4byte 0x30200073 /* 800000e4: mret */
.globl body
body:
  .org 0xe8
  .4byte 0x00043283 /* 800000e8: ld t0,0(s0) # 40001000 <_start-0x3ffff000> */
  .org 0xec
  .4byte 0x0330000f /* 800000ec: fence rw,rw */
.globl inspect
inspect:
  .org 0xf0
  .4byte 0x0004b983 /* 800000f0: ld s3,0(s1) */
  .org 0xf4
  .4byte 0x04096913 /* 800000f4: ori s2,s2,64 */
  .org 0xf8
  .4byte 0x01299863 /* 800000f8: bne s3,s2,80000108 <pte_fail> */
  .org 0xfc
  .4byte 0x00029a63 /* 800000fc: bnez t0,80000110 <data_fail> */
.globl pass
pass:
  .org 0x100
  .4byte 0x00100513 /* 80000100: li a0,1 */
  .org 0x104
  .4byte 0x0340006f /* 80000104: j 80000138 <finish> */
.globl pte_fail
pte_fail:
  .org 0x108
  .4byte 0x00300513 /* 80000108: li a0,3 */
  .org 0x10c
  .4byte 0x02c0006f /* 8000010c: j 80000138 <finish> */
.globl data_fail
data_fail:
  .org 0x110
  .4byte 0x00500513 /* 80000110: li a0,5 */
  .org 0x114
  .4byte 0x0240006f /* 80000114: j 80000138 <finish> */
.globl setup_fail
setup_fail:
  .org 0x118
  .4byte 0x00700513 /* 80000118: li a0,7 */
  .org 0x11c
  .4byte 0x01c0006f /* 8000011c: j 80000138 <finish> */
.globl missing_trap
missing_trap:
  .org 0x120
  .4byte 0x00900513 /* 80000120: li a0,9 */
  .org 0x124
  .4byte 0x0140006f /* 80000124: j 80000138 <finish> */
.globl trap
trap:
  .org 0x128
  .4byte 0x34202a73 /* 80000128: csrr s4,mcause */
  .org 0x12c
  .4byte 0x34102af3 /* 8000012c: csrr s5,mepc */
  .org 0x130
  .4byte 0x34302b73 /* 80000130: csrr s6,mtval */
.globl unexpected_trap
unexpected_trap:
  .org 0x134
  .4byte 0x00b00513 /* 80000134: li a0,11 */
.globl finish
finish:
  .org 0x138
  .4byte 0x00000297 /* 80000138: auipc t0,0x0 */
  .org 0x13c
  .4byte 0x04828293 /* 8000013c: addi t0,t0,72 # 80000180 <tohost> */
  .org 0x140
  .4byte 0x00a2b023 /* 80000140: sd a0,0(t0) */
  .org 0x144
  .4byte 0x0000006f /* 80000144: j 80000144 <finish+0xc> */

.section .tohost,"aw"
.globl tohost
tohost:
  .zero 8
.globl fromhost
fromhost:
  .zero 8

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
