OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x80000000;
  .text.init : { KEEP(*(.text.init)) }
  . = ALIGN(4K);
  .text : { *(.text .text.*) }
  . = ALIGN(4K);
  .rodata : { *(.rodata .rodata.*) }
  . = ALIGN(4K);
  .data : { *(.data .data.*) }
  . = ALIGN(4K);
  .bss : { *(.bss .bss.* COMMON) }
  . = ALIGN(4K);
  .stack : { stack_space = .; . += 0x4000; stack_space_end = .; }
  _end = .;
}
