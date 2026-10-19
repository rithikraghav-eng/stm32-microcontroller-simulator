.syntax unified
.thumb
.text
.global _start
_start:
    and r0, r1
    eor r0, r1
    orr r0, r1
    bic r0, r1
    mvn r0, r1
    lsl r0, r1
    lsr r0, r1
    asr r0, r1
    add r0, r1
    sub r0, r1
    mov r0, r1
    cmp r0, r1
    lsls r0, r1, #0
    lsrs r0, r1, #0
    asrs r0, r1, #0
    lsls r0, r1, #1
    lsrs r0, r1, #1
    asrs r0, r1, #1
