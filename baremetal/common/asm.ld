OUTPUT_ARCH( "riscv" )
ENTRY( _start )

SECTIONS
{

  . = 0x80000000;
  .text.init : { KEEP(*(.text.init)) KEEP(*(.init.text)) }
  . = ALIGN(0x1000);
  .text : { KEEP(*(.text)) }
  . = ALIGN(0x1000);
  .tohost : { KEEP(*(.tohost)) }
  . = ALIGN(0x1000);
  .data : { KEEP(*(.data)) }
  .bss : { KEEP(*(.bss)) }
  _end = .;

}
