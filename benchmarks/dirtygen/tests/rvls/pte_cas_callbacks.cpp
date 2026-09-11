// SPDX-License-Identifier: MIT

#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <stdexcept>

#include "context.hpp"

namespace {

constexpr u64 kPte = 0x81005080;
constexpr u64 kOtherPte = kPte + 8;
constexpr u64 kClean = 0x0000000020480057;
constexpr u64 kDirty = 0x00000000204800d7;

const u8* bytes(const u64& value) {
    return reinterpret_cast<const u8*>(&value);
}

void require(bool condition, const char* message) {
    if(!condition) throw std::runtime_error(message);
}

void expectFailure(const std::function<void()>& body, const char* message) {
    try {
        body();
    } catch(const std::runtime_error&) {
        return;
    }
    throw std::runtime_error(message);
}

TraceMmuStore store(u64 address, u64 value, bool error) {
    TraceMmuStore item;
    item.address = address;
    item.length = 8;
    item.error = error;
    memcpy(item.bytes, &value, 8);
    return item;
}

} // namespace

int main() {
    Context context;
    CpuMemoryView view0(context.memory, 1, 1);
    CpuMemoryView view1(context.memory, 1, 1);
    view0.bindHartId(0);
    view1.bindHartId(1);
    SpikeIf hart0(&view0, 0, &context.pteCasEvents, &context.pteCasStates);
    SpikeIf hart1(&view1, 1, &context.pteCasEvents, &context.pteCasStates);
    hart0.regions.push_back({RegionType::mem, kPte, 16});
    hart1.regions.push_back({RegionType::mem, kPte, 16});

    u64 observed = 0;
    bool updated = false;
    bool error = false;

    // A local loser consumes no architectural MMU store and receives the
    // complete PTE that defeated its stale expected value.
    context.mmuPteCas(0, 3, 10, 100, kPte, 8,
                      kClean, kDirty, kDirty, false, false);
    hart0.mmuStoreQueue.push(store(kPte, kDirty, false));
    require(hart0.mmio_mmu_pte_update_probe(
                kPte, 8, bytes(kClean), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)),
            "mismatch probe was not handled");
    require(observed == kDirty, "mismatch did not return the full observed PTE");
    require(context.pteCasEvents.empty(), "mismatch event was not consumed");
    require(hart0.mmuStoreQueue.size() == 1,
            "mismatch consumed an architectural store");
    hart0.mmuStoreQueue.pop();

    // A hart that issued no CAS can still synchronize its reference PTE cache
    // from the terminal value observed by RTL.  No winner identity is assumed.
    observed = 0;
    require(hart1.mmio_mmu_pte_update_probe(
                kPte, 8, bytes(kClean), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)),
            "observer probe was not handled");
    require(observed == kDirty, "observer did not receive trace-derived PTE state");

    // A software write starts a new PTE epoch and must discard the old
    // trace-derived value.
    view0.storeExecute(0, kPte, 8, bytes(kClean));
    view0.storeCommit(0);
    require(hart0.mmio_store(kPte, 8, bytes(kClean)),
            "software PTE store was not handled");
    view0.storeBroadcast(0);
    require(context.pteCasStates.empty(), "software PTE write did not clear trace state");

    // A winner may be reported before loser mismatches, while Spike serializes
    // the winner first and therefore needs no probe for those losing harts.
    // Keep every terminal in history, but leave only the successful update in
    // the architectural pending queue.  This is the H4 repeated-epoch case.
    const auto historyBeforeRedundantLoser = context.pteCasHistory.size();
    context.mmuPteCas(0, 9, 30, 110, kPte, 8,
                      kClean, kDirty, kClean, false, true);
    context.mmuPteCas(1, 9, 31, 111, kPte, 8,
                      kClean, kDirty, kDirty, false, false);
    require(context.pteCasHistory.size() == historyBeforeRedundantLoser + 2,
            "redundant loser terminal was not retained in history");
    require(context.pteCasEvents.size() == 1,
            "redundant loser remained pending after a known winner");
    observed = 0;
    require(hart1.mmio_mmu_pte_update_probe(
                kPte, 8, bytes(kClean), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)) && observed == kDirty,
            "observer did not use the winner's trace-derived PTE");
    observed = 0;
    require(hart0.mmio_mmu_pte_update_probe(
                kPte, 8, bytes(kClean), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)) &&
            observed == kClean && hart0.pteCasReservationValid,
            "winner was not reserved after an observer ran first");
    hart0.mmuStoreQueue.push(store(kPte, kDirty, false));
    require(hart0.mmio_mmu_compare_exchange(
                kPte, 8, bytes(kClean), bytes(kDirty), &updated, &error) &&
            updated && !error,
            "winner was not consumed after an observer ran first");
    require(context.pteCasEvents.empty() && hart0.mmuStoreQueue.empty(),
            "observer-first winner sequence did not drain");
    view0.storeExecute(0, kPte, 8, bytes(kClean));
    view0.storeCommit(0);
    require(hart0.mmio_store(kPte, 8, bytes(kClean)),
            "repeated-epoch software PTE store was not handled");
    view0.storeBroadcast(0);
    require(context.pteCasStates.empty(),
            "repeated-epoch software PTE store retained trace state");

    // First observe a concurrent A update, then successfully add D.  The
    // second expected value must contain the newly observed A bit.
    const u64 accessed = kClean & ~u64(0x80);
    const u64 initial = accessed & ~u64(0x40);
    context.mmuPteCas(0, 4, 11, 101, kPte, 8,
                      initial, kDirty, accessed, false, false);
    context.mmuPteCas(0, 4, 12, 102, kPte, 8,
                      accessed, kDirty, accessed, false, true);
    observed = 0;
    require(hart0.mmio_mmu_pte_update_probe(
                kPte, 8, bytes(initial), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)),
            "first sequential probe was not handled");
    require(observed == accessed, "new A was not preserved after mismatch");
    observed = 0;
    require(hart0.mmio_mmu_pte_update_probe(
                kPte, 8, bytes(accessed), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)),
            "successful sequential probe was not handled");
    require(observed == accessed && hart0.pteCasReservationValid,
            "successful CAS was not reserved");
    hart0.mmuStoreQueue.push(store(kPte, kDirty, false));
    require(hart0.mmio_mmu_compare_exchange(
                kPte, 8, bytes(accessed), bytes(kDirty), &updated, &error),
            "successful CAS commit was not handled");
    require(updated && !error, "successful CAS returned the wrong terminal state");
    require(context.pteCasEvents.empty() && hart0.mmuStoreQueue.empty() &&
            !hart0.pteCasReservationValid,
            "successful CAS did not drain exactly once");
    expectFailure([&] {
        hart0.mmio_mmu_compare_exchange(
            kPte, 8, bytes(accessed), bytes(kDirty), &updated, &error);
    }, "successful CAS was consumed more than once");
    expectFailure([&] {
        context.mmuPteCas(0, 4, 12, 102, kPte, 8,
                          accessed, kDirty, accessed, false, true);
    }, "consumed PTE CAS identity was accepted again");
    u64 memoryPte = 0;
    context.memory.read(kPte, 8, reinterpret_cast<u8*>(&memoryPte));
    require(memoryPte == kDirty, "successful CAS did not update reference memory");

    // An error reserves and consumes the matching architectural error store,
    // but never reports an update.
    context.mmuPteCas(0, 5, 13, 103, kOtherPte, 8,
                      kClean, kDirty, kClean, true, false);
    observed = 0;
    require(hart0.mmio_mmu_pte_update_probe(
                kOtherPte, 8, bytes(kClean), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)),
            "error probe was not handled");
    hart0.mmuStoreQueue.push(store(kOtherPte, kDirty, true));
    updated = true;
    error = false;
    require(hart0.mmio_mmu_compare_exchange(
                kOtherPte, 8, bytes(kClean), bytes(kDirty), &updated, &error),
            "error CAS commit was not handled");
    require(!updated && error, "error CAS returned the wrong terminal state");

    // A local terminal event must match the complete expected and desired
    // values supplied by the page-table walk.
    context.mmuPteCas(0, 7, 20, 105, kPte, 8,
                      kClean, kDirty, kClean, false, true);
    expectFailure([&] {
        u64 value = 0;
        hart0.mmio_mmu_pte_update_probe(
            kPte, 8, bytes(initial), bytes(kDirty),
            reinterpret_cast<u8*>(&value));
    }, "wrong PTE CAS expected value was accepted");
    context.pteCasEvents.clear();
    context.mmuPteCas(0, 7, 21, 106, kPte, 8,
                      kClean, kDirty, kClean, false, true);
    expectFailure([&] {
        u64 value = 0;
        hart0.mmio_mmu_pte_update_probe(
            kPte, 8, bytes(kClean), bytes(accessed),
            reinterpret_cast<u8*>(&value));
    }, "wrong PTE CAS desired value was accepted");
    context.pteCasEvents.clear();

    // A software overwrite is an epoch boundary for pending mismatch-only
    // terminals as well as for the trace-derived PTE value.
    context.mmuPteCas(1, 10, 32, 112, kOtherPte, 8,
                      kClean, kDirty, kDirty, false, false);
    require(context.pteCasEvents.size() == 1,
            "standalone mismatch was not retained for a local probe");
    view0.storeExecute(0, kOtherPte, 8, bytes(kClean));
    view0.storeCommit(0);
    require(hart0.mmio_store(kOtherPte, 8, bytes(kClean)),
            "mismatch epoch-reset store was not handled");
    view0.storeBroadcast(0);
    require(context.pteCasEvents.empty() &&
            context.pteCasStates.find(kOtherPte) == context.pteCasStates.end(),
            "software epoch reset retained an old mismatch");

    // A full logger or logger-store fault can terminate an access before RTL
    // issues a PTE CAS.  The probe must fall through without modifying its
    // output, reserving a CAS, consuming a store, or creating PTE state.
    hart0.invalidatePteCasState(kPte, 16);
    observed = 0xfeedfacecafebeef;
    require(!hart0.mmio_mmu_pte_update_probe(
                kPte, 8, bytes(kClean), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)),
            "pre-CAS fault probe was unexpectedly handled");
    require(observed == 0xfeedfacecafebeef,
            "pre-CAS fault probe modified the observed value");
    require(!hart0.pteCasReservationValid && context.pteCasEvents.empty() &&
            context.pteCasStates.empty() && hart0.mmuStoreQueue.empty(),
            "pre-CAS fault probe changed RVLS state");
    hart0.checkFinalState();

    // A logger-store error is an architectural MMU-store outcome but still
    // has no PTE CAS terminal.  It must be consumed exactly once.
    hart0.mmuStoreQueue.push(store(kPte, kDirty, true));
    require(!hart0.mmio_mmu_store(kPte, 8, bytes(kDirty)),
            "logger-store error was not returned");
    require(hart0.mmuStoreQueue.empty(),
            "logger-store error was not consumed exactly once");
    hart0.checkFinalState();

    // Falling through is not permission to perform an untraced update.  If
    // Spike reaches compare-exchange, the absent reservation remains fatal.
    expectFailure([&] {
        hart0.mmio_mmu_compare_exchange(
            kPte, 8, bytes(kClean), bytes(kDirty), &updated, &error);
    }, "missing PTE CAS terminal was accepted after probe fallthrough");

    context.mmuPteCas(0, 6, 14, 104, kPte, 8,
                      kClean, kDirty, kDirty, false, false);
    expectFailure([&] {
        context.mmuPteCas(0, 6, 14, 104, kPte, 8,
                          kClean, kDirty, kDirty, false, false);
    }, "duplicate PTE CAS identity was accepted");
    expectFailure([&] { context.checkFinalState(); },
                  "residual PTE CAS event passed final drain");
    context.pteCasEvents.clear();

    hart0.mmuStoreQueue.push(store(kPte, kDirty, false));
    expectFailure([&] { hart0.checkFinalState(); },
                  "residual MMU store passed final drain");
    hart0.mmuStoreQueue.pop();

    context.mmuPteCas(0, 8, 22, 107, kPte, 8,
                      kClean, kDirty, kClean, false, true);
    observed = 0;
    require(hart0.mmio_mmu_pte_update_probe(
                kPte, 8, bytes(kClean), bytes(kDirty),
                reinterpret_cast<u8*>(&observed)),
            "reservation drain setup was not handled");
    expectFailure([&] { hart0.checkFinalState(); },
                  "residual PTE CAS reservation passed final drain");
    context.pteCasEvents.clear();
    hart0.pteCasReservationValid = false;
    hart0.checkFinalState();

    std::cout << "RVLS_PTE_CAS_MINIMAL PASS\n";
    return 0;
}
