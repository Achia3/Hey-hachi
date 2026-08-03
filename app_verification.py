import time
import logging
from datetime import datetime
import ollama

# Configure logger to output system verification metrics to system_verification.log
log_filename = "system_verification.log"
logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

def run_system_verification():
    """
    APEX TECH LOCAL AI ENGINE - SYSTEM VERIFICATION SCRIPT
    Interfaces with local Ollama daemon (localhost:11434) using Qwen 2.5 3B model.
    Measures inference latency and writes operational status to system_verification.log.
    """
    target_host = "http://localhost:11434"
    target_model = "qwen2.5:3b"
    prompt = "Hello Qwen, state your model version and confirm system status."

    print("=" * 50)
    print("APEX TECH LOCAL AI ENGINE - SYSTEM CHECK")
    print("=" * 50)
    print(f"Target Host   : {target_host}")
    print(f"Target Model  : {target_model}")

    logging.info(f"Initiating APEX Tech Local AI Engine System Check.")
    logging.info(f"Target Host: {target_host} | Target Model: {target_model}")

    start_time = time.time()
    try:
        # Programmatic HTTP connection via python ollama client
        response = ollama.chat(
            model=target_model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ]
        )
        end_time = time.time()
        inference_time = end_time - start_time

        qwen_response = response['message']['content'].strip()
        connection_status = "SUCCESSFUL"
        status_code = "200 OK - OPERATIONAL"

        # Console Output matching Section 5 lab specifications
        print(f"Connection    : {connection_status}")
        print("-" * 50)
        print("[Qwen Response]:")
        print(f'"{qwen_response}"')
        print("-" * 50)
        print(f"Inference Time: {inference_time:.2f} seconds")
        print(f"Status Code   : {status_code}")
        print("=" * 50)

        # Record operational log telemetry
        logging.info(f"Connection Status: {connection_status}")
        logging.info(f"Prompt Sent: {prompt}")
        logging.info(f"Qwen Response: {qwen_response}")
        logging.info(f"Inference Latency: {inference_time:.2f} seconds")
        logging.info(f"System State: {status_code}")

    except Exception as e:
        end_time = time.time()
        inference_time = end_time - start_time
        print(f"Connection    : FAILED")
        print(f"Error Details : {e}")
        print("=" * 50)
        logging.error(f"Connection Failed: {e} | Elapsed: {inference_time:.2f}s")

if __name__ == "__main__":
    run_system_verification()
