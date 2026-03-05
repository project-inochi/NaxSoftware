OUTPUT_ARCH( "riscv" )
ENTRY( _start )
MEMORY {
  onChipRam (W!RX)/*(RX)*/ : ORIGIN = 0x80000000, LENGTH = 16M
}

SECTIONS
{

  .init.text :
  {
    . = ALIGN(4);
    *(.text.init)
  } > onChipRam
   .crt_section :
   {
    . = ALIGN(4);
    *crt.o(.text)
   } > onChipRam

}
