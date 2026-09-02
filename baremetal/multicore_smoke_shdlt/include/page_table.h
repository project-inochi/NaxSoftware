#ifndef SHDLT_PAGE_TABLE_H
#define SHDLT_PAGE_TABLE_H
#include <stdint.h>
void shdlt_build_page_tables(uint64_t hart, const uint8_t *code, uint64_t code_len);
#endif
