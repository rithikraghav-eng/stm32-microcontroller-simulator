volatile int result;
volatile int zero_probe;
volatile int initialized_probe = 7;

__attribute__((noinline)) int add_pair(int left, int right)
{
    return left + right;
}

int main(void)
{
    volatile int sum = 0;
    for (volatile int index = 0; index < 4; ++index) {
        sum += index;
    }

    if (sum > 2) {
        result = add_pair(sum, initialized_probe);
    }

    __asm volatile("bkpt #0");
    return result;
}
