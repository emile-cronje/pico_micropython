import time
from machine import Pin
from rp2 import PIO, StateMachine, asm_pio

# Make the state-machine count configurable. Pico 2 exposes 12 SM (3 PIO blocks × 4 SM).
# MicroPython maps state machine IDs sequentially across PIO blocks (0-3 => PIO0, 4-7 => PIO1, 8-11 => PIO2).
MAX_STATE_MACHINES = 12
STATE_MACHINES_REQUESTED = 12  # Set this to any even number up to 12
multiple = 50
PIO_FREQ_BASE = 20000


def resolve_counts():
    sm = min(STATE_MACHINES_REQUESTED, MAX_STATE_MACHINES)
    if sm % 2:
        print(f"Warning: requested {STATE_MACHINES_REQUESTED} SM is odd; rounding down to {sm-1}.")
        sm -= 1
    if sm < 2:
        raise ValueError("Need at least 2 state machines (1 producer/consumer pair)")
    pairs = sm // 2
    return sm, pairs

@asm_pio(
    out_shiftdir=PIO.SHIFT_LEFT,
    out_init=PIO.OUT_LOW,
    set_init=PIO.OUT_LOW,
    autopull=True,
    pull_thresh=32,
)
def producer():
    """
    Producer PIO. Pulses the clock pin to synchronize data transfer.
    Uses autopull to automatically fetch data from TX FIFO.
    The delays [4] make the clock pulse 5 cycles long (1+4).
    """
    # Ensure clock starts LOW
    set(pins, 0)
    label("word_loop")
    # No explicit pull - autopull will handle it when OSR is empty
    mov(x, 31)
    label("bitloop")
    # Set the data pin from OSR (autopull will refill OSR when needed)
    out(pins, 1)
    # Pulse the clock pin high then low, with delays
    set(pins, 1) [4]
    set(pins, 0) [4]
    jmp(x_dec, "bitloop")
    
    # Jump back to get the next word
    jmp("word_loop")


def create_consumer_pio(clock_pin_id):
    """
    Generates a consumer PIO program that is hard-coded to listen
    to a specific clock pin. Continuously receives 32-bit words.
    """
    @asm_pio(
        in_shiftdir=PIO.SHIFT_LEFT,
        autopush=True,
        push_thresh=32,
    )
    def consumer():
        # Ensure we start synchronized - wait for clock to be low first
        wait(0, gpio, clock_pin_id)
        label("word_loop")
        mov(x, 31)
        label("bitloop")
        # 1. Wait for the clock to go high
        wait(1, gpio, clock_pin_id)
        # 2. Read the data bit
        in_(pins, 1)
        # 3. Wait for the clock to go low
        wait(0, gpio, clock_pin_id)
        jmp(x_dec, "bitloop")
        # After 32 bits, autopush occurs and we loop back for next word
        jmp("word_loop")

    return consumer


def main():
    sm_count, entityCount = resolve_counts()
    print(f"Init complete... using {sm_count} state machines -> {entityCount} producer/consumer pairs")
    pio_freq = PIO_FREQ_BASE

    # Initialize clock pins to LOW before setting up state machines
    # Each pair uses data pin GP(2*i) and clock pin GP(2*i+1)
    for i in range(entityCount):
        clock_pin_id = i * 2 + 1
        Pin(clock_pin_id, Pin.OUT).value(0)
        
    print("Clock pins initialized to LOW.")

    producers = []
    consumers = []

    # --- Setup Producer/Consumer Pairs ---
    # Each pair uses two state machines. Pico 2 has 12 SM total (3 PIO blocks × 4 SM), so we can run 6 pairs.
    if entityCount < 1:
        raise ValueError("entityCount must be >= 1")
    
    max_pairs = 6  # 12 state machines / 2 per pair
    
    if entityCount > max_pairs:
        raise ValueError(f"entityCount too large: max {max_pairs} pairs (12 state machines)")

    for i in range(entityCount):
        data_pin_id = i * 2
        clock_pin_id = i * 2 + 1
        producer_sm_id = i * 2
        consumer_sm_id = i * 2 + 1
        pio_index = producer_sm_id // 4  # For logging only; mapping is automatic in MicroPython

        print(f"Setting up pair {i} on PIO({pio_index}):")
        print(f"  Producer on SM{producer_sm_id} (Data: GP{data_pin_id}, Clock: GP{clock_pin_id})")
        print(f"  Consumer on SM{consumer_sm_id} (Data: GP{data_pin_id}, Clock: GP{clock_pin_id})")

        # --- Setup Producer ---
        producers.append(StateMachine(
            producer_sm_id,
            producer,
            freq=pio_freq,
            out_base=Pin(data_pin_id),
            set_base=Pin(clock_pin_id),
        ))

        # --- Setup Consumer ---
        consumer_program = create_consumer_pio(clock_pin_id)
        consumers.append(StateMachine(
            consumer_sm_id,
            consumer_program,
            freq=pio_freq,
            in_base=Pin(data_pin_id),
        ))

    # --- Main Operation ---
    # Build a shared payload queue and let all producer/consumer pairs drain it collaboratively.
    base_strings = [
        "Hello PIO World!123456",
        "Testing 1 2 3...5734567567356735",
        "Hello PIO World!gadjghladfjghladjg",
        "Testing 1 2 3...34879a87098",
    ]

    shared_string = " | ".join(base_strings) * multiple

    def string_to_words(s):
        data = s.encode('utf-8')
        words = []
        padded = data + b'\x00' * ((4 - len(data) % 4) % 4)
        
        for i in range(0, len(padded), 4):
            word = (padded[i] << 24) | (padded[i+1] << 16) | (padded[i+2] << 8) | padded[i+3]
            words.append(word)
        return words, len(data)

    shared_words, shared_len = string_to_words(shared_string)
    print(f"Shared queue length: {len(shared_words)} words ({shared_len} bytes)")

    FIFO_DEPTH = 4
    streaming_mode = True  # Always stream from the shared queue

    print("\nDistributing shared queue across producers...")

    # Track per-producer assignments and per-consumer receipts for stats, plus global receipt order.
    assigned_words = [[] for _ in range(entityCount)]
    received_words = [[] for _ in range(entityCount)]
    global_received = []

    # Prime TX FIFOs up to their depth.
    queue_idx = 0
    for i in range(entityCount):
        preload = min(FIFO_DEPTH, len(shared_words) - queue_idx)
        print(f"Producer {i} pre-loading {preload} words")
        
        for _ in range(preload):
            word = shared_words[queue_idx]
            producers[i].put(word)
            assigned_words[i].append(word)
            queue_idx += 1

    # Activate all SMs.
    for sm in consumers:
        sm.active(1)
    for sm in producers:
        sm.active(1)
    print("State machines activated.")

    # Streaming loop: keep feeding any producer with FIFO space until the shared queue is empty.
    while queue_idx < len(shared_words):
        time.sleep(0.002)

        # Drain consumer RX to avoid overflows and record global order.
        for i in range(entityCount):
            while consumers[i].rx_fifo():
                word = consumers[i].get()
                received_words[i].append(word)
                global_received.append(word)

        # Fill producers with any available FIFO space.
        for i in range(entityCount):
            fifo_count = producers[i].tx_fifo()
            fifo_space = FIFO_DEPTH - fifo_count
            while fifo_space > 0 and queue_idx < len(shared_words):
                word = shared_words[queue_idx]
                producers[i].put(word)
                assigned_words[i].append(word)
                queue_idx += 1
                fifo_space -= 1

    # Give time for tail to flush.
    tail_words = FIFO_DEPTH * 2
    time_per_word = (32 * 10) / pio_freq
    tail_wait = tail_words * time_per_word
    time.sleep(tail_wait)

    # Final RX drain.
    for i in range(entityCount):
        while consumers[i].rx_fifo():
            word = consumers[i].get()
            received_words[i].append(word)
            global_received.append(word)

    # --- Verification ---
    print("\nVerifying shared queue delivery...")
    all_correct = True

    def words_to_string(words, length):
        data = bytearray()
        for word in words:
            data.append((word >> 24) & 0xFF)
            data.append((word >> 16) & 0xFF)
            data.append((word >> 8) & 0xFF)
            data.append(word & 0xFF)
        return data[:length].decode('utf-8')

    total_assigned = sum(len(a) for a in assigned_words)
    total_received = sum(len(r) for r in received_words)
    print(f"Assigned words: {total_assigned}, Received words: {total_received}")

    # Check per-consumer correctness against what was assigned to its paired producer.
    for i in range(entityCount):
        expected = assigned_words[i]
        actual = received_words[i]
        if len(expected) != len(actual):
            print(f"Consumer {i}: count mismatch (expected {len(expected)}, got {len(actual)})")
            all_correct = False
            continue
        for idx, (e, a) in enumerate(zip(expected, actual)):
            if e != a:
                print(f"Consumer {i}: word {idx} mismatch (expected {hex(e)}, got {hex(a)})")
                all_correct = False
                break
        else:
            print(f"Consumer {i}: received {len(actual)} words OK")

    if total_received != len(shared_words):
        print("Shared queue delivery had errors (global count mismatch).")
        all_correct = False
    else:
        # Global order check against the original queue
        order_match = global_received == shared_words
        if order_match:
            print("Shared queue delivered intact in original order.")
        else:
            print("Shared queue delivered with reordering (data intact per-word).")

    # --- Cleanup ---
    for sm in producers + consumers:
        sm.active(0)
    print("\nState machines deactivated. Example finished.")


if __name__ == "__main__":
    start_time = time.ticks_us()
    main()
    end_time = time.ticks_us()
    duration_ms = time.ticks_diff(end_time, start_time) / 1000000
    print(f"\nTotal execution time: {duration_ms:.2f} s")
