/**
 * STM32G431 - Main entry stub
 * Integrate fpv_watchdog_main() into your CubeMX-generated main.c
 *
 * Minimal CubeMX configuration:
 *   - Clock:  HSI 16 MHz
 *   - USART2: 115200, 8N1, async, interrupt mode
 *   - PB8:    GPIO output (push-pull, no pull, high speed) — Pi power control
 *   - PC13:   GPIO output (push-pull) — status LED
 *   - IWDG:   Enable with ~10s timeout (hardware safety net)
 */

/* In your CubeMX main.c, after MX_GPIO_Init() and MX_USART2_UART_Init(): */

/*
    extern void fpv_watchdog_main(void);
    fpv_watchdog_main();   // never returns
*/
