OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  .text 0x80000000 : { *(.text) }
  .tohost 0x80000200 : { *(.tohost) }
  .data 0x80004000 : { *(.data) }
}
