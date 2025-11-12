#pragma once

.macro TEST_SET _csr, _fail, _mask, _tmp
    csrr \_tmp, \_csr
    and \_tmp, \_tmp, \_mask
    bne \_mask, \_tmp, \_fail
.endm

.macro TEST_CLR _csr, _fail, _mask, _tmp
    csrr \_tmp, \_csr
    and \_tmp, \_tmp, \_mask
    bnez \_tmp, \_fail
.endm
