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
