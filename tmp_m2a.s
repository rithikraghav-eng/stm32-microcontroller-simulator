.syntax unified
.thumb
.text
.global _start
_start:
    mov r0, r1
    mov r8, r1
    mov r1, r8
    add r0, r1
    add r8, r1
    sub r0, r1
    sub r8, r1
    add r0, r1, r2
    sub r0, r1, r2
    ands r0, r1
    eors r0, r1
    orrs r0, r1
    bics r0, r1
    mvns r0, r1
    lsls r0, r1
    lsrs r0, r1
    asrs r0, r1
