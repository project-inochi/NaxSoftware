OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x80000000;
  .text : { *(.text.init) *(.text*) }
  . = ALIGN(64);
  .tohost : { *(.tohost) }
  . = ALIGN(16384);
  .data : { *(.data*) }
  .bss : { *(.bss*) }
}
