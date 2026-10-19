.syntax unified
.thumb
.text
.global _start
_start:
    ands r0, r1
    eors r0, r1
    orrs r0, r1
    bics r0, r1
    mvns r0, r1
    lsls r0, r1
    lsrs r0, r1
    asrs r0, r1
    adds r0, r1
    subs r0, r1
