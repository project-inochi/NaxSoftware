#ifndef DIRTYGEN_EPOCH_H
#define DIRTYGEN_EPOCH_H

#define DIRTYGEN_EPOCH_ABI_VERSION 1
#define DIRTYGEN_EPOCH_PTE_SCAN_SERIAL 0
#define DIRTYGEN_EPOCH_SHDLT_LOG 1
#define DIRTYGEN_EPOCH_BITMAP_WORDS 2
#define DIRTYGEN_EPOCH_TRACKED_PAGES 128
#define DIRTYGEN_EPOCH_RUNS 6

#ifndef __ASSEMBLER__

#include <stdint.h>

#define DIRTYGEN_EPOCH_PTE_D UINT64_C(0x080)
#define DIRTYGEN_EPOCH_LOG_RESERVED_MASK UINT64_C(0xff00000000000fff)

struct dirtygen_epoch_metrics {
  uint64_t pte_entries_scanned;
  uint64_t raw_log_entries;
  uint64_t committed_log_entries;
  uint64_t canonical_dirty_pages;
  uint64_t duplicates;
  uint64_t invalid_log_entries;
  uint64_t reserved_bit_errors;
  uint64_t index_errors;
  uint64_t rearm_pages;
  uint64_t rearm_missing_d;
  uint64_t rearm_readback_errors;
};

void dirtygen_epoch_zero_bitmap(
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS]);
uint64_t dirtygen_epoch_bitmap_has(
    const uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS], uint64_t page);
void dirtygen_epoch_bitmap_add(
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS], uint64_t page);
uint64_t dirtygen_epoch_bitmap_count(
    const uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS]);

void dirtygen_epoch_scan_ptes(
    volatile const uint64_t *ptes, uint64_t tracked_pages,
    uint64_t *snapshot, struct dirtygen_epoch_metrics *metrics);
void dirtygen_epoch_normalize_pte_snapshot(
    const uint64_t *snapshot, uint64_t tracked_pages,
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS],
    struct dirtygen_epoch_metrics *metrics);
uint64_t dirtygen_epoch_copy_log(
    volatile const uint64_t *log, uint64_t index, uint64_t capacity,
    uint64_t *snapshot, struct dirtygen_epoch_metrics *metrics);
void dirtygen_epoch_normalize_log(
    const uint64_t *snapshot, uint64_t entries, uint64_t tracked_gpa,
    uint64_t tracked_pages,
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS],
    struct dirtygen_epoch_metrics *metrics);
void dirtygen_epoch_rearm_from_bitmap(
    volatile uint64_t *ptes, uint64_t tracked_pages,
    const uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS],
    struct dirtygen_epoch_metrics *metrics);

#endif
#endif
