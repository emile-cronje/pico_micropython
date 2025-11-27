import time
from machine import Pin
from rp2 import PIO, StateMachine, asm_pio

# Attempt 8: Use a single PIO instance.
# The failure of all previous clocked attempts suggests an obscure issue,
# possibly related to interactions between PIO0 and PIO1.
# This version places all state machines on a single PIO block (PIO0)
# as a diagnostic step. This limits us to 2 pairs instead of 4.

entityCount = 4  # Number of producer/consumer pairs (each pair uses 2 state machines)

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
    print("Init complete...")
    pio_freq = 20000

    # Initialize clock pins to LOW before setting up state machines
    # Each pair uses data pin GP(2*i) and clock pin GP(2*i+1)
    for i in range(entityCount):
        clock_pin_id = i * 2 + 1
        Pin(clock_pin_id, Pin.OUT).value(0)
        
    print("Clock pins initialized to LOW.")

    producers = []
    consumers = []

    # --- Setup Producer/Consumer Pairs ---
    # Each pair uses two state machines. RP2040 has 8 SM total (0-7). Limit pairs to 4.
    if entityCount < 1:
        raise ValueError("entityCount must be >= 1")
    if entityCount > 4:
        raise ValueError("entityCount too large: max 4 pairs (8 state machines)")

    for i in range(entityCount):
        data_pin_id = i * 2
        clock_pin_id = i * 2 + 1
        producer_sm_id = i * 2
        consumer_sm_id = i * 2 + 1
        
        print(f"Setting up pair {i} on PIO(0):")
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
    # Test with both raw data and strings
    test_strings = [
        "Hello PIO World!123456"*40,
        "Testing 1 2 3...5734567567356735"*40,
        "Hello PIO World!gadjghladfjghladjg"*40,
        "Testing 1 2 3...34879a87098"*40
    ]

    # Only use as many strings as we have pairs
    if len(test_strings) > entityCount:
        print(f"Warning: {len(test_strings)} test strings provided but only {entityCount} pairs configured. Truncating.")
        test_strings = test_strings[:entityCount]
    
    # Convert strings to 32-bit words
    def string_to_words(s):
        """Convert a string to a list of 32-bit words (big-endian)"""
        data = s.encode('utf-8')
        words = []
        # Pad to multiple of 4 bytes
        padded = data + b'\x00' * ((4 - len(data) % 4) % 4)
        # Pack into 32-bit words
        for i in range(0, len(padded), 4):
            word = (padded[i] << 24) | (padded[i+1] << 16) | (padded[i+2] << 8) | padded[i+3]
            words.append(word)
        return words, len(data)  # Return words and original length
    
    test_data = []
    original_lengths = []
    
    for s in test_strings:
        words, length = string_to_words(s)
        test_data.append(words)
        original_lengths.append(length)
        print(f"String '{s}' -> {len(words)} words ({length} bytes)")
    
    # Check if any string exceeds FIFO capacity
    FIFO_DEPTH = 4
    max_words = max(len(words) for words in test_data)
    
    if max_words > FIFO_DEPTH:
        print(f"\nNote: Maximum {max_words} words exceeds TX FIFO depth of {FIFO_DEPTH}.")
        print(f"Will use streaming mode to send data.")
        streaming_mode = True
    else:
        streaming_mode = False
    
    num_words_to_send = max(len(words) for words in test_data)
    
    print(f"\nSending up to {num_words_to_send} words per producer...")
    
    if streaming_mode:
        # Streaming mode: Load initial batch, activate, then stream remaining words
        print("Using streaming mode...")
        
        # Track how many words have been sent for each producer
        words_sent = [0] * entityCount
        
        # Load initial batch (up to FIFO_DEPTH words)
        for i in range(entityCount):
            initial_count = min(FIFO_DEPTH, len(test_data[i]))
            print(f"Producer {i} pre-loading {initial_count} words:")
            for j in range(initial_count):
                producers[i].put(test_data[i][j])
                print(f"  - {hex(test_data[i][j])}")
                words_sent[i] += 1
        
        # Activate state machines
        for sm in consumers:
            sm.active(1)
        for sm in producers:
            sm.active(1)
        print("State machines activated.")
        
        # Track received words during streaming to prevent RX FIFO overflow
        received_words = [[] for _ in range(entityCount)]
        
        # Stream remaining words as the producer consumes them
        all_done = False
        while not all_done:
            all_done = True
            time.sleep(0.005)  # Small delay between checks
            
            # Read from consumers to prevent RX FIFO overflow
            for i in range(entityCount):
                while consumers[i].rx_fifo():
                    received_words[i].append(consumers[i].get())
            
            for i in range(entityCount):
                # Check if there are more words to send for this producer
                if words_sent[i] < len(test_data[i]):
                    all_done = False
                    # Check TX FIFO space (returns number of words in FIFO)
                    fifo_count = producers[i].tx_fifo()
                    fifo_space = FIFO_DEPTH - fifo_count
                    
                    # Send as many words as we can fit
                    while fifo_space > 0 and words_sent[i] < len(test_data[i]):
                        word_to_send = test_data[i][words_sent[i]]
                        producers[i].put(word_to_send)
                        print(f"Producer {i} streaming word {words_sent[i]}: {hex(word_to_send)}")
                        words_sent[i] += 1
                        fifo_space -= 1
        
        print("All words streamed.")
        
        # Wait for final transmission to complete
        time_per_word = (32 * 10) / pio_freq
        final_wait = FIFO_DEPTH * time_per_word * 1.5
        print(f"Waiting {final_wait:.3f}s for final words to transmit...")
        time.sleep(final_wait)
        
        # Read any remaining words from consumers
        for i in range(entityCount):
            while consumers[i].rx_fifo():
                received_words[i].append(consumers[i].get())
        
        print("Streaming complete.")
        for i in range(entityCount):
            print(f"  Consumer {i} received {len(received_words[i])} words")
        
    else:
        # Original mode: Load all words before activating
        # Pad shorter lists with zeros to match the longest
        for i in range(entityCount):
            words_to_send = test_data[i]
            padded_words = words_to_send + [0] * (num_words_to_send - len(words_to_send))
            print(f"Producer {i} loading {len(padded_words)} words ({len(words_to_send)} data + {len(padded_words) - len(words_to_send)} padding):")
            for word in padded_words:
                print(f"  - {hex(word)}")
                producers[i].put(word)
                
        print("All words loaded into TX FIFOs.")
        
        # Activate state machines
        for sm in consumers:
            sm.active(1)
        
        # Check TX FIFO before activating producers
        print("\nTX FIFO status before activating producers:")
        for i in range(entityCount):
            print(f"  Producer {i} TX FIFO: {producers[i].tx_fifo()} words")
        
        for sm in producers:
            sm.active(1)
        print("State machines activated.")
        
        # Check immediately after activation
        time.sleep(0.001)
        print("\nTX FIFO status 1ms after activation:")
        for i in range(entityCount):
            print(f"  Producer {i} TX FIFO: {producers[i].tx_fifo()} words")
        
        # Wait for transmission to complete
        # Each word takes (32 bits * 10 cycles/bit) / freq seconds
        time_per_word = (32 * 10) / pio_freq
        total_time = num_words_to_send * time_per_word * 1.5  # 50% margin
        print(f"Waiting {total_time:.3f}s for transmission...")
        time.sleep(total_time)
    
    # Check FIFO status for debugging
    print("\nFIFO status after transmission:")
    for i in range(entityCount):
        print(f"  Producer {i} TX FIFO: {producers[i].tx_fifo()} words remaining")
        print(f"  Consumer {i} RX FIFO: {consumers[i].rx_fifo()} words available")

    print("\nChecking consumers...")
    all_correct = True
    
    # Helper to convert words back to string
    def words_to_string(words, length):
        """Convert 32-bit words back to string"""
        data = bytearray()
        for word in words:
            data.append((word >> 24) & 0xFF)
            data.append((word >> 16) & 0xFF)
            data.append((word >> 8) & 0xFF)
            data.append(word & 0xFF)
        return data[:length].decode('utf-8')
    
    for i in range(entityCount):
        print(f"\nConsumer {i} results:")
        expected_words = test_data[i]
        # In streaming mode received_words was captured earlier; in batch, build now
        if not streaming_mode:
            received_words = [[] for _ in range(entityCount)]
            while consumers[i].rx_fifo():
                received_words[i].append(consumers[i].get())
        
        # In streaming mode, we send exact words; in batch mode, we may have padding
        if streaming_mode:
            expected_count = len(expected_words)
        else:
            expected_count = len(expected_words)
        
        actual_word_count = len(expected_words)
        received_data_words = received_words[i][:actual_word_count]
        
        if streaming_mode:
            print(f"  Expected {actual_word_count} words, received {len(received_words[i])} words")
        else:
            print(f"  Expected {actual_word_count} words, received {len(received_data_words)} data words (+ {len(received_words[i]) - len(received_data_words)} padding)")
        
        if len(received_data_words) != actual_word_count:
            print(f"  FAIL! Word count mismatch")
            all_correct = False
        else:
            # Check each word
            words_match = True
            for j, (expected, received) in enumerate(zip(expected_words, received_data_words)):
                if received != expected:
                    print(f"  Word {j}: FAIL! Received {hex(received)}, Expected {hex(expected)}")
                    words_match = False
                    all_correct = False
            
            if words_match:
                # Decode the string
                received_string = words_to_string(received_data_words, original_lengths[i])
                expected_string = test_strings[i]
                print(f"  String received: '{received_string}'")
                print(f"  String expected: '{expected_string}'")
                if received_string == expected_string:
                    print(f"  ✓ String matches!")
                else:
                    print(f"  ✗ String mismatch!")
                    all_correct = False
    
    print("\n" + "-" * 20)
    if all_correct:
        print("Success! All consumers received the correct data.")
    else:
        print("Failure: Some or all consumers reported errors.")

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
