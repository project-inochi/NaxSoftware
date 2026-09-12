#include "dirtygen_epoch.h"

void dirtygen_epoch_zero_bitmap(
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS]) {
  for (uint64_t word = 0; word < DIRTYGEN_EPOCH_BITMAP_WORDS; ++word)
    bitmap[word] = 0;
}

uint64_t dirtygen_epoch_bitmap_has(
    const uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS], uint64_t page) {
  if (page >= DIRTYGEN_EPOCH_TRACKED_PAGES)
    return 0;
  return (bitmap[page >> 6] >> (page & 63)) & 1;
}

void dirtygen_epoch_bitmap_add(
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS], uint64_t page) {
  if (page < DIRTYGEN_EPOCH_TRACKED_PAGES)
    bitmap[page >> 6] |= UINT64_C(1) << (page & 63);
}

static uint64_t popcount64(uint64_t value) {
  uint64_t count = 0;

  while (value != 0) {
    value &= value - 1;
    ++count;
  }
  return count;
}

uint64_t dirtygen_epoch_bitmap_count(
    const uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS]) {
  uint64_t count = 0;

  for (uint64_t word = 0; word < DIRTYGEN_EPOCH_BITMAP_WORDS; ++word)
    count += popcount64(bitmap[word]);
  return count;
}

void dirtygen_epoch_scan_ptes(
    volatile const uint64_t *ptes, uint64_t tracked_pages,
    uint64_t *snapshot, struct dirtygen_epoch_metrics *metrics) {
  for (uint64_t page = 0; page < tracked_pages; ++page) {
    snapshot[page] = ptes[page];
    ++metrics->pte_entries_scanned;
  }
}

void dirtygen_epoch_normalize_pte_snapshot(
    const uint64_t *snapshot, uint64_t tracked_pages,
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS],
    struct dirtygen_epoch_metrics *metrics) {
  dirtygen_epoch_zero_bitmap(bitmap);
  for (uint64_t page = 0; page < tracked_pages; ++page) {
    if ((snapshot[page] & DIRTYGEN_EPOCH_PTE_D) != 0)
      dirtygen_epoch_bitmap_add(bitmap, page);
  }
  metrics->canonical_dirty_pages = dirtygen_epoch_bitmap_count(bitmap);
}

uint64_t dirtygen_epoch_copy_log(
    volatile const uint64_t *log, uint64_t index, uint64_t capacity,
    uint64_t *snapshot, struct dirtygen_epoch_metrics *metrics) {
  uint64_t entries = index;

  metrics->raw_log_entries += index;
  if (entries > capacity) {
    ++metrics->index_errors;
    entries = capacity;
  }
  for (uint64_t slot = 0; slot < entries; ++slot)
    snapshot[slot] = log[slot];
  metrics->committed_log_entries += entries;
  return entries;
}

void dirtygen_epoch_normalize_log(
    const uint64_t *snapshot, uint64_t entries, uint64_t tracked_gpa,
    uint64_t tracked_pages,
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS],
    struct dirtygen_epoch_metrics *metrics) {
  uint64_t limit = tracked_gpa + tracked_pages * UINT64_C(4096);

  dirtygen_epoch_zero_bitmap(bitmap);
  for (uint64_t slot = 0; slot < entries; ++slot) {
    uint64_t value = snapshot[slot];

    if ((value & DIRTYGEN_EPOCH_LOG_RESERVED_MASK) != 0) {
      ++metrics->reserved_bit_errors;
      ++metrics->invalid_log_entries;
      continue;
    }
    if (value < tracked_gpa || value >= limit) {
      ++metrics->invalid_log_entries;
      continue;
    }
    uint64_t page = (value - tracked_gpa) >> 12;
    if (dirtygen_epoch_bitmap_has(bitmap, page) != 0)
      ++metrics->duplicates;
    dirtygen_epoch_bitmap_add(bitmap, page);
  }
  metrics->canonical_dirty_pages = dirtygen_epoch_bitmap_count(bitmap);
}

void dirtygen_epoch_rearm_from_bitmap(
    volatile uint64_t *ptes, uint64_t tracked_pages,
    const uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS],
    struct dirtygen_epoch_metrics *metrics) {
  for (uint64_t page = 0; page < tracked_pages; ++page) {
    uint64_t before;
    uint64_t after;

    if (dirtygen_epoch_bitmap_has(bitmap, page) == 0)
      continue;
    before = ptes[page];
    if ((before & DIRTYGEN_EPOCH_PTE_D) == 0)
      ++metrics->rearm_missing_d;
    after = before & ~DIRTYGEN_EPOCH_PTE_D;
    ptes[page] = after;
    if (ptes[page] != after)
      ++metrics->rearm_readback_errors;
    ++metrics->rearm_pages;
  }
}
