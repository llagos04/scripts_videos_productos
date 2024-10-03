import asyncio
import logging
import crawler
import fetcher
import analizer
import results
import time
from colorama import init, Fore, Style
from dotenv import load_dotenv
from CONFIG import ROOT_URL, LLM_BATCH_SIZE, TARGET_PRODUCTS_N, CONCURRENT_REQUESTS, GENERAL_BATCH_SIZE
import signal

load_dotenv()
init()  # Initialize Colorama

# Custom log level formatting with color and style
class ColorFormatter(logging.Formatter):
    def __init__(self, fmt):
        super().__init__(fmt)

    def format(self, record):
        levelname = record.levelname
        if levelname == "INFO":
            record.levelname = f"{Fore.GREEN}{levelname}{Style.RESET_ALL}"
        elif levelname == "WARNING":
            record.levelname = f"{Fore.YELLOW}{levelname}{Style.RESET_ALL}"
        elif levelname == "ERROR":
            record.levelname = f"{Fore.RED}{levelname}{Style.RESET_ALL}"
        elif levelname == "DEBUG":
            record.levelname = f"{Fore.BLUE}{levelname}{Style.RESET_ALL}"
        return super().format(record)

# Configure logging for both file and console output with color
logging.basicConfig(level=logging.INFO,
                    format=f'{Style.BRIGHT}%(levelname)s -\t%(message)s{Style.RESET_ALL}',
                    handlers=[
                        logging.FileHandler('scraper.log', mode='w'),
                        logging.StreamHandler()
                    ])
for handler in logging.root.handlers:
    handler.setFormatter(ColorFormatter(handler.formatter._fmt))

logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

# Configure logging for both file and console output
logging.basicConfig(level=logging.INFO,
                    format='%(levelname)s -\t%(message)s',
                    handlers=[
                        logging.FileHandler('scraper.log', mode='w'),
                        logging.StreamHandler()
                    ])

logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

async def main():
    """
    Main function to orchestrate the web scraping process.
    """
    try:
        logging.info("Starting web scraping process...")

        # Check if the domain is JavaScript-driven
        logging.info(f"Checking if {ROOT_URL} is JavaScript-driven...")
        is_javascript_driven = await crawler.is_javascript_driven_async(ROOT_URL)
        logging.info(f"{ROOT_URL} is {'not ' if not is_javascript_driven else ''}JavaScript-driven.")

        # Initialize variables
        total_products_found = 0
        iterations = 0
        processed_urls = set()
        start_time = time.time()

        # Initialize crawler
        crawler_instance = crawler.Crawler(ROOT_URL, is_javascript_driven)

        # Initialize results manager
        execution_number = results.get_execution_number(ROOT_URL)
        results_manager = results.ResultsManager(ROOT_URL, execution_number)

        # Define a signal handler for graceful shutdown
        def signal_handler(sig, frame):
            logging.info('You pressed Ctrl+C! Saving results and exiting...')
            results_manager.save_results()
            exit(0)
        signal.signal(signal.SIGINT, signal_handler)

        while total_products_found < TARGET_PRODUCTS_N:
            start_iteration_time = time.time()
            iterations += 1
            logging.info("")
            logging.info("")
            logging.info(Fore.GREEN + Style.BRIGHT + f"############### START ITERATION {iterations} ###############\n" + Style.RESET_ALL)
            # Fetch a batch of URLs
            logging.info(f"Fetching a batch of {GENERAL_BATCH_SIZE} URLs from {ROOT_URL}...")
            start_batch_time = time.time()
            batch_urls = await crawler_instance.get_next_batch_urls(GENERAL_BATCH_SIZE)
            elapsed_batch_time = time.time() - start_batch_time
            logging.info(Fore.GREEN + f"Crawled {len(batch_urls)} URLs in {elapsed_batch_time:.2f} seconds\n" + Style.RESET_ALL)

            if not batch_urls:
                logging.info("")
                logging.info("No more URLs to process.")
                break

            # Remove already processed URLs
            batch_urls_to_process = [url for url in batch_urls if url not in processed_urls]
            # Update processed URLs
            processed_urls.update(batch_urls_to_process)

            # Fetch Titles
            logging.info(f"Fetching titles for {len(batch_urls_to_process)} URLs...")
            start_time_fetch_titles = time.time()
            url_titles = await fetcher.fetch_titles(batch_urls_to_process, max_concurrent_requests=CONCURRENT_REQUESTS)
            elapsed_time_fetch_titles = time.time() - start_time_fetch_titles
            logging.info(Fore.GREEN + f"Fetched titles for {len(url_titles)} URLs in {elapsed_time_fetch_titles:.2f} seconds\n" + Style.RESET_ALL)
            
            # discard existing titles
            logging.info(f"Discarding existing titles from {len(url_titles)} URLs... {results_manager.seen_titles} already exist in results")
            url_titles = [title for title in url_titles if title not in results_manager.seen_titles]

            # Select Product URLs
            logging.info(f"Selecting product URLs from {len(url_titles)} URLs...")
            start_time_select_products = time.time()
            product_urls_titles = await analizer.select_product_urls(url_titles, LLM_BATCH_SIZE)
            elapsed_time_select_products = time.time() - start_time_select_products
            logging.info(Fore.GREEN + f"Selected {len(product_urls_titles)} product URLs in {elapsed_time_select_products:.2f} seconds\n" + Style.RESET_ALL)

            # Fetch Product Details
            logging.info(f"Fetching product details for {len(product_urls_titles)} product URLs...")
            start_time_fetch_details = time.time()
            product_details = await fetcher.fetch_product_details(product_urls_titles, max_concurrent_requests=CONCURRENT_REQUESTS)
            elapsed_time_fetch_details = time.time() - start_time_fetch_details
            logging.info(Fore.GREEN + f"Fetched {len(product_details)} product details in {elapsed_time_fetch_details:.2f} seconds\n" + Style.RESET_ALL)

            # Update total products found
            total_products_found += len(product_details)
            logging.info(f"Total products found so far: {total_products_found}")

            # Save Results
            logging.info("Saving results...")
            start_time_save_results = time.time()
            results_manager.append_results(product_details)
            elapsed_time_save_results = time.time() - start_time_save_results
            logging.info(Fore.GREEN  + f"Saved {results_manager.total_products} unique products to {results_manager.results_file}\n" + Style.RESET_ALL)
            
            elapsed_iteration_time = time.time() - start_iteration_time
            logging.info(Fore.GREEN + Style.BRIGHT + f"Completed iteration {iterations} in {elapsed_iteration_time:.2f} seconds" + Style.RESET_ALL)
            
            # Check if TARGET_PRODUCTS_N is reached
            if total_products_found >= TARGET_PRODUCTS_N:
                logging.info(f"Target number of products ({TARGET_PRODUCTS_N}) reached.")
                break

        # Final save
        results_manager.save_results()

        total_elapsed_time = time.time() - start_time
        logging.info(Fore.GREEN + Style.BRIGHT + f"Completed web scraping process in {total_elapsed_time:.2f} seconds")

    except Exception as e:
        logging.exception(f"An error occurred during the web scraping process: {e}")

if __name__ == '__main__':
    asyncio.run(main())