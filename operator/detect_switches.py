import pygame, time
pygame.init(); pygame.joystick.init()
joy = pygame.joystick.Joystick(0); joy.init()
prev = None
print(f"Axes:{joy.get_numaxes()} Btns:{joy.get_numbuttons()}")
print("Рухай SB через усі 3 позиції, потім SD через усі 3 позиції...")
while True:
    pygame.event.pump()
    btns = [joy.get_button(i) for i in range(joy.get_numbuttons())]
    axes = [round(joy.get_axis(i), 2) for i in range(joy.get_numaxes())]
    state = (tuple(btns), tuple(axes))
    if state != prev:
        active = [i for i, b in enumerate(btns) if b]
        print(f"A:{axes}  ActiveBtns:{active}")
        prev = state
    time.sleep(0.05)
