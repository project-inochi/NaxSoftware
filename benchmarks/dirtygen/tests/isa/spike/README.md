# Twelve Spike PTE/Svadu acceptance regressions

These are the twelve cases already used in the Spike recheck-removal audit,
now with buildable inputs inside NaxSoftware. No simulator hook is required.
They test ordinary RAM, not concurrent RTL walkers or an SBI implementation.

`pte_rsw.S` is the original source. Build only `FENCED=1` for acceptance:
RV32/RV64 times S/VS/G stages gives six tests. The software RSW write precedes
SFENCE.VMA/HFENCE.VVMA/HFENCE.GVMA, which precedes the affected store.

The remaining six original source files were not retained alongside the
previously executed ELF files. Their inputs here are explicit instruction-word
assembly, with decoded instructions and addresses in comments, recovered from
those ELF files. This is **not** a claim to have recovered the original source.
The fixed linker addresses are essential for their encoded PC-relative
instructions. `fixtures.json` retains the old ELF hashes and hashes of every
loadable section; the runner refuses to execute a reconstruction unless all
three section hashes match. Non-loadable symbol/attribute sections can differ.
The former scratch directory is not needed to rebuild these inputs.

| Fixture | Contract |
| --- | --- |
| remote-fence-before-access | Shared PTE RSW modification; release request; remote acquire and SFENCE.VMA **before** access; release acknowledgement and acquire inspection |
| hardware-d-shared-a0/a1 | Initial A=0/1; successful load prime, remote hardware D update, then local store; no intervening software PTE modification |
| store-then-load-fault0/fault1 | Hart 0 store before hart 1 load, optionally after hart 1's instruction-page fault; final full PTE retains A and D |
| predirty-a0-load | Initially A=0,D=1; load sets A without clearing D |

Some recovered symbol names (`writer_modify`, `reader_store`) describe older
variants; the instruction comments and the table above define these fixtures.
Do not add unfenced software-PTE-write variants to this acceptance matrix.

From the VexiiRiscv root, using an **existing** Spike executable:

```sh
python3 ext/NaxSoftware/benchmarks/dirtygen/tools/run_spike_isa_minimals.py \
  --spike /path/to/spike \
  --output-root ext/NaxSoftware/benchmarks/dirtygen/build/isa-consistency/spike-new
```

The runner records compiler, binary/source/ELF hashes, build/run commands and
exit status. HTIF exit zero means PASS. Timeout means incomplete validation.
For this phase the already-built Spike executable is also archived under
`build/isa-consistency/tools/spike`; neither the source nor its gitlink changed.
It depends on the host libraries listed by `ldd`, not on the old build directory.
