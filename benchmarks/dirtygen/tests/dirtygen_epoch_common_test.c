#include "dirtygen_epoch.h"

#include <stdio.h>
#include <string.h>

#define CHECK(condition) do {                                             \
  if (!(condition)) {                                                     \
    fprintf(stderr, "CHECK failed at %s:%d: %s\n", __FILE__, __LINE__,  \
            #condition);                                                  \
    return 1;                                                             \
  }                                                                       \
} while (0)

static int test_scan_all_entries(void) {
  uint64_t ptes[DIRTYGEN_EPOCH_TRACKED_PAGES];
  uint64_t snapshot[DIRTYGEN_EPOCH_TRACKED_PAGES];
  uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS];
  struct dirtygen_epoch_metrics metrics = {0};

  memset(ptes, 0, sizeof(ptes));
  ptes[DIRTYGEN_EPOCH_TRACKED_PAGES - 1] = DIRTYGEN_EPOCH_PTE_D;
  dirtygen_epoch_scan_ptes(ptes, DIRTYGEN_EPOCH_TRACKED_PAGES, snapshot,
                           &metrics);
  dirtygen_epoch_normalize_pte_snapshot(
      snapshot, DIRTYGEN_EPOCH_TRACKED_PAGES, bitmap, &metrics);
  CHECK(metrics.pte_entries_scanned == DIRTYGEN_EPOCH_TRACKED_PAGES);
  CHECK(metrics.canonical_dirty_pages == 1);
  CHECK(dirtygen_epoch_bitmap_has(bitmap,
                                  DIRTYGEN_EPOCH_TRACKED_PAGES - 1) == 1);
  return 0;
}

static int test_log_bounds_and_validation(void) {
  uint64_t log[6] = {
      UINT64_C(0x10000), UINT64_C(0x10000), UINT64_C(0x11000),
      UINT64_C(0x12001), UINT64_C(0x100000000010000), UINT64_C(0x90000),
  };
  uint64_t snapshot[6] = {0};
  uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS];
  struct dirtygen_epoch_metrics metrics = {0};
  uint64_t copied = dirtygen_epoch_copy_log(log, 5, 6, snapshot, &metrics);

  CHECK(copied == 5);
  CHECK(snapshot[5] == 0);
  dirtygen_epoch_normalize_log(snapshot, copied, UINT64_C(0x10000), 128,
                               bitmap, &metrics);
  CHECK(metrics.raw_log_entries == 5);
  CHECK(metrics.committed_log_entries == 5);
  CHECK(metrics.canonical_dirty_pages == 2);
  CHECK(metrics.duplicates == 1);
  CHECK(metrics.invalid_log_entries == 2);
  CHECK(metrics.reserved_bit_errors == 2);

  memset(&metrics, 0, sizeof(metrics));
  copied = dirtygen_epoch_copy_log(log, 6, 6, snapshot, &metrics);
  dirtygen_epoch_normalize_log(snapshot, copied, UINT64_C(0x10000), 128,
                               bitmap, &metrics);
  CHECK(metrics.invalid_log_entries == 3);
  CHECK(metrics.reserved_bit_errors == 2);

  memset(&metrics, 0, sizeof(metrics));
  copied = dirtygen_epoch_copy_log(log, 7, 6, snapshot, &metrics);
  CHECK(copied == 6);
  CHECK(metrics.raw_log_entries == 7);
  CHECK(metrics.committed_log_entries == 6);
  CHECK(metrics.index_errors == 1);
  return 0;
}

static int test_rearm_preserves_complete_pte(void) {
  uint64_t ptes[DIRTYGEN_EPOCH_TRACKED_PAGES];
  uint64_t original[DIRTYGEN_EPOCH_TRACKED_PAGES];
  uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS] = {0, 0};
  struct dirtygen_epoch_metrics metrics = {0};

  for (uint64_t page = 0; page < DIRTYGEN_EPOCH_TRACKED_PAGES; ++page) {
    ptes[page] = (UINT64_C(0x1234500000000000) | (page << 10) |
                   UINT64_C(0x347) | DIRTYGEN_EPOCH_PTE_D);
    original[page] = ptes[page];
  }
  dirtygen_epoch_bitmap_add(bitmap, 0);
  dirtygen_epoch_bitmap_add(bitmap, 65);
  dirtygen_epoch_rearm_from_bitmap(ptes, DIRTYGEN_EPOCH_TRACKED_PAGES,
                                   bitmap, &metrics);
  CHECK(metrics.rearm_pages == 2);
  CHECK(metrics.rearm_missing_d == 0);
  CHECK(metrics.rearm_readback_errors == 0);
  for (uint64_t page = 0; page < DIRTYGEN_EPOCH_TRACKED_PAGES; ++page) {
    uint64_t expected = original[page];
    if (page == 0 || page == 65)
      expected &= ~DIRTYGEN_EPOCH_PTE_D;
    CHECK(ptes[page] == expected);
  }
  return 0;
}

static int test_scan_and_log_agree(void) {
  uint64_t ptes[DIRTYGEN_EPOCH_TRACKED_PAGES] = {0};
  uint64_t pte_snapshot[DIRTYGEN_EPOCH_TRACKED_PAGES];
  uint64_t log[] = {UINT64_C(0x10000), UINT64_C(0x17000),
                    UINT64_C(0x8f000)};
  uint64_t log_snapshot[3];
  uint64_t scan_bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS];
  uint64_t log_bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS];
  struct dirtygen_epoch_metrics scan = {0};
  struct dirtygen_epoch_metrics logger = {0};

  ptes[0] = DIRTYGEN_EPOCH_PTE_D;
  ptes[7] = DIRTYGEN_EPOCH_PTE_D;
  ptes[127] = DIRTYGEN_EPOCH_PTE_D;
  dirtygen_epoch_scan_ptes(ptes, DIRTYGEN_EPOCH_TRACKED_PAGES,
                           pte_snapshot, &scan);
  dirtygen_epoch_normalize_pte_snapshot(
      pte_snapshot, DIRTYGEN_EPOCH_TRACKED_PAGES, scan_bitmap, &scan);
  dirtygen_epoch_copy_log(log, 3, 3, log_snapshot, &logger);
  dirtygen_epoch_normalize_log(log_snapshot, 3, UINT64_C(0x10000), 128,
                               log_bitmap, &logger);
  CHECK(memcmp(scan_bitmap, log_bitmap, sizeof(scan_bitmap)) == 0);
  return 0;
}

int main(void) {
  CHECK(test_scan_all_entries() == 0);
  CHECK(test_log_bounds_and_validation() == 0);
  CHECK(test_rearm_preserves_complete_pte() == 0);
  CHECK(test_scan_and_log_agree() == 0);
  puts("dirtygen epoch common tests: PASS");
  return 0;
}
