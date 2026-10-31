/* Standalone official PS5 binary, used only for bootstrapping a missing DNS. */
#ifndef PM_DNS_SEED
#define PM_DNS_SEED "../build/pm-seed/nanodns.elf"
#endif
.section .rodata
.balign 16
.global pm_dns_seed
.global pm_dns_seed_end
pm_dns_seed:
.incbin PM_DNS_SEED
pm_dns_seed_end:
.section .note.GNU-stack,"",@progbits
