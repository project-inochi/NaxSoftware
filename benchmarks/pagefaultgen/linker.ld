OUTPUT_ARCH("riscv")
ENTRY(_start)
SECTIONS {
  . = 0x80000000;
  .text.init : ALIGN(64) { KEEP(*(.text.init)) }
  .text : ALIGN(4096) { *(.text .text.*) *(.rodata .rodata.*) }
  .data : ALIGN(4096) { *(.data .data.*) }
  .bss (NOLOAD) : ALIGN(64) { *(.bss .bss.*) *(COMMON) }
  .page_tables (NOLOAD) : ALIGN(16384) { *(.page_tables) }
  _end = .;
}
