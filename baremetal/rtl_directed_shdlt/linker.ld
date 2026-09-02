OUTPUT_ARCH(riscv)
ENTRY(_start)

SECTIONS
{
  . = 0x80000000;
  .text : {
    KEEP(*(.text.init))
    *(.text .text.*)
  }
  .rodata : { *(.rodata .rodata.*) }
  .data : {
    *(.data .data.*)
    PROVIDE(__global_pointer$ = . + 0x800);
    *(.sdata .sdata.*)
  }
  . = ALIGN(8);
  bss_start = .;
  .bss : {
    *(.sbss .sbss.*)
    *(.bss .bss.*)
    *(COMMON)
  }
  bss_end = .;
  .bss.stack : { *(.bss.stack) }
}
