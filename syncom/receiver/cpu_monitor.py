# Pico htop-like CPU Load Monitor (Dual-Core Method)
#
# This version correctly measures system load on a dual-core MCU like the Pico.
# It works by measuring the degradation in performance of a benchmark task
# when a worker thread is running on the other core.

import machine
import utime
import _thread
import gc

# --- Global Variables ---
# This dictionary will hold our calibration and load data.
system_info = {
    'max_loops': 0,      # The max loops in the benchmark (0% load)
    'cpu_load': 0.0,     # The calculated CPU load percentage
    'mem_percent': 0.0,
    'mem_free': 0
}

# --- 1. The Worker Thread (to create CPU load) ---
def busy_worker():
    """A simple function to consume CPU cycles on the second core."""
    print("Worker thread started on Core 1.")
    while True:
        # This loop will keep Core 1 busy.
        _ = 123.456 * 789.012 / 3.14159
        # No sleep is needed here, we want it to run at full speed.

# --- 2. The Measurement Logic ---
def benchmark_task():
    """A computationally-intensive task to measure performance."""
    # This loop is our unit of "work". The number of times it can run
    # in a fixed period is a measure of available CPU power.
    count = 0
    start_time = utime.ticks_ms()
    # Run the benchmark for 200ms
    while utime.ticks_diff(utime.ticks_ms(), start_time) < 200:
        _ = 987.654 / 123.456 # Some arbitrary work
        count += 1
    return count

def calibrate():
    """Measures the maximum performance baseline with no load."""
    print("Calibrating CPU... Please wait a moment.")
    # Run the benchmark to get the max loops possible
    loops = benchmark_task()
    system_info['max_loops'] = loops
    print(f"Calibration complete. Max benchmark loops: {system_info['max_loops']}")
    utime.sleep(1)

def update_stats(_timer):
    """
    This function is called by a Timer interrupt.
    It runs the benchmark, calculates the load, and gets memory stats.
    """
    # Run the benchmark to see current performance
    current_loops = benchmark_task()
    max_loops = system_info['max_loops']

    # --- Calculate CPU Load ---
    if max_loops > 0:
        # The new formula:
        # The load is the percentage of performance we've LOST.
        performance_loss = 1 - (current_loops / max_loops)
        load_percentage = performance_loss * 100
        system_info['cpu_load'] = max(0, min(100, load_percentage))

    # --- Get Memory Info ---
    gc.collect()
    mem_free = gc.mem_free()
    mem_alloc = gc.mem_alloc()
    mem_total = mem_free + mem_alloc
    system_info['mem_percent'] = (mem_alloc / mem_total) * 100 if mem_total > 0 else 0
    system_info['mem_free'] = mem_free

# --- 3. The Main Setup and Display Loop ---
def main():
    # Calibrate first to get our baseline
    calibrate()

    # Start the worker thread to generate load on Core 1
    _thread.start_new_thread(busy_worker, ())

    # Set up a periodic timer that calls our stats updater every 1000ms (1s)
    timer = machine.Timer()
    timer.init(period=1000, mode=machine.Timer.PERIODIC, callback=update_stats)

    print("Starting CPU monitor... Press Ctrl+C to stop.")

    try:
        # The main loop is now just for printing the results.
        # The actual work is done in the timer callback.
        while True:
            load = system_info['cpu_load']
            mem_percent = system_info['mem_percent']
            mem_free = system_info['mem_free']

            # Create the bar visuals
            cpu_bar = '#' * int(load / 4) + ' ' * (25 - int(load / 4))
            mem_bar = '#' * int(mem_percent / 4) + ' ' * (25 - int(mem_percent / 4))

            # Format the output string
            output_string = f"CPU: [{cpu_bar}] {load:5.1f}% | MEM: [{mem_bar}] {mem_percent:5.1f}% | Free: {mem_free//1024}K "

            # Print to console, using carriage return to overwrite the line
            print(output_string, end='\r')

            # Sleep for a bit. The 1-second update rate is handled by the timer.
            utime.sleep_ms(200)

    except KeyboardInterrupt:
        print("\nStopping monitor.")
    finally:
        # Clean up the timer when the program stops
        timer.deinit()
        print("Timer stopped. Program finished.")

# Run the main function
if __name__ == "__main__":
    main()
