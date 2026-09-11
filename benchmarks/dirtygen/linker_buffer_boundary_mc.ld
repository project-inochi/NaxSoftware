OUTPUT_ARCH("riscv")
ENTRY(_start)

SECTIONS
{
  . = 0x80000000;

  .text.init : ALIGN(64) { KEEP(*(.text.init)) }
  .text.guest : ALIGN(4096) { KEEP(*(.text.guest)) }
  .text : ALIGN(4096) { *(.text .text.*) }
  .rodata : ALIGN(4096) { *(.rodata .rodata.*) }
  .data : ALIGN(4096) { *(.data .data.*) *(.sdata .sdata.*) }
  .bss (NOLOAD) : ALIGN(4096)
  {
    *(.bss .bss.*)
    *(.sbss .sbss.*)
    *(COMMON)
  }
  .stack (NOLOAD) : ALIGN(4096)
  {
    boundary_mc_stack_space = .;
    . += 0x4000;
    boundary_mc_stack_end = .;
  }
  _end = .;

  ASSERT(SIZEOF(.text.guest) <= 0x1000,
         "buffer boundary guest payload exceeds its mapped page")
}
