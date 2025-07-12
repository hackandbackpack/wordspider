#!/usr/bin/env python3
"""
Web Spider Wordlist Generator

A tool that crawls websites within a domain, extracts and counts words
while filtering common terms via a configurable ignore list.
"""

import argparse
import json
import re
import sys
import time
import warnings
from collections import Counter, defaultdict
from urllib.parse import urljoin, urlparse, urlunparse
from typing import Set, Dict, List, Optional

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Suppress XML parsing warnings for RSS feeds
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


class URLValidator:
    """Handles URL validation and domain checking."""
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize URL by removing fragments and ensuring proper format."""
        parsed = urlparse(url)
        return urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            parsed.query,
            ''  # Remove fragment
        ))
    
    @staticmethod
    def get_domain(url: str) -> str:
        """Extract domain from URL."""
        return urlparse(url).netloc.lower()
    
    @staticmethod
    def is_same_domain(url1: str, url2: str) -> bool:
        """Check if two URLs belong to the same domain (handles www subdomain)."""
        domain1 = URLValidator.get_domain(url1).lower()
        domain2 = URLValidator.get_domain(url2).lower()
        
        # Remove www. prefix for comparison
        if domain1.startswith('www.'):
            domain1 = domain1[4:]
        if domain2.startswith('www.'):
            domain2 = domain2[4:]
            
        return domain1 == domain2
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Validate if URL is properly formatted."""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False


class IgnoreListManager:
    """Manages the ignore word list from file."""
    
    def __init__(self, ignore_file: str = "ignore_words.txt"):
        self.ignore_file = ignore_file
        self.ignore_words: Set[str] = set()
        self.load_ignore_list()
    
    def load_ignore_list(self) -> None:
        """Load ignore words from file."""
        try:
            with open(self.ignore_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip().lower()
                    if line and not line.startswith('#'):
                        self.ignore_words.add(line)
        except FileNotFoundError:
            print(f"Warning: Ignore file '{self.ignore_file}' not found. Creating default.")
            self.create_default_ignore_list()
        except Exception as e:
            print(f"Error loading ignore file: {e}")
            sys.exit(1)
    
    def create_default_ignore_list(self) -> None:
        """Create a default ignore list with common words."""
        default_words = [
            "# Common English words to ignore",
            "a", "an", "and", "are", "as", "at", "be", "been", "by", "for",
            "from", "has", "he", "in", "is", "it", "its", "of", "on", "that",
            "the", "to", "was", "will", "with", "the", "this", "but", "they",
            "have", "had", "what", "said", "each", "which", "she", "do", "how",
            "their", "if", "up", "out", "many", "then", "them", "these", "so",
            "some", "her", "would", "make", "like", "into", "him", "time", "has",
            "two", "more", "go", "no", "way", "could", "my", "than", "first",
            "been", "call", "who", "oil", "sit", "now", "find", "down", "day",
            "did", "get", "come", "made", "may", "part"
        ]
        
        try:
            with open(self.ignore_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(default_words))
            self.load_ignore_list()
        except Exception as e:
            print(f"Error creating default ignore file: {e}")
            sys.exit(1)
    
    def should_ignore(self, word: str) -> bool:
        """Check if word should be ignored."""
        return word.lower() in self.ignore_words


class TextProcessor:
    """Handles text extraction and processing from HTML."""
    
    def __init__(self, ignore_manager: IgnoreListManager):
        self.ignore_manager = ignore_manager
        self.word_pattern = re.compile(r'\b[a-zA-Z]+\b')
    
    def extract_text_from_html(self, html_content: str) -> str:
        """Extract clean text from HTML content."""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get text and clean it
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            return text
        except Exception as e:
            print(f"Error processing HTML: {e}")
            return ""
    
    def extract_words(self, text: str) -> List[str]:
        """Extract and filter words from text."""
        words = self.word_pattern.findall(text.lower())
        return [word for word in words if not self.ignore_manager.should_ignore(word) and len(word) > 2]
    
    def extract_links(self, html_content: str, base_url: str) -> Set[str]:
        """Extract all links from HTML content."""
        links = set()
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href']
                full_url = urljoin(base_url, href)
                normalized_url = URLValidator.normalize_url(full_url)
                if URLValidator.is_valid_url(normalized_url):
                    links.add(normalized_url)
        except Exception as e:
            print(f"Error extracting links: {e}")
        
        return links


class WebSpider:
    """Main web crawling functionality."""
    
    def __init__(self, ignore_manager: IgnoreListManager, delay: float = 1.0, quiet: bool = False):
        self.ignore_manager = ignore_manager
        self.text_processor = TextProcessor(ignore_manager)
        self.visited_urls: Set[str] = set()
        self.word_counts: Counter = Counter()
        self.page_word_counts: Dict[str, Dict[str, int]] = {}
        self.delay = delay
        self.quiet = quiet
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        self.total_pages_found = 0
        self.total_words_processed = 0
    
    def fetch_page(self, url: str) -> Optional[str]:
        """Fetch HTML content from URL."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Only process HTML content using allowlist - skip everything else
            content_type = response.headers.get('content-type', '').lower()
            if not ('text/html' in content_type or 'application/xhtml' in content_type):
                if not self.quiet:
                    print(f"    Skipping non-HTML content: {content_type}")
                return None
                
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def crawl_page(self, url: str, target_domain: str, page_num: int, queue_size: int) -> Set[str]:
        """Crawl a single page and return found links."""
        if url in self.visited_urls:
            return set()
        
        if self.quiet:
            print(f"[{page_num}] {url}")
        else:
            print(f"\n[{page_num}] Crawling: {url}")
            print(f"    Domain: {URLValidator.get_domain(url)}")
            print(f"    Queue remaining: {queue_size}")
        
        self.visited_urls.add(url)
        
        html_content = self.fetch_page(url)
        if not html_content:
            if not self.quiet:
                print("    Failed to fetch content")
            return set()
        
        # Extract and count words
        text = self.text_processor.extract_text_from_html(html_content)
        words = self.text_processor.extract_words(text)
        
        page_counter = Counter(words)
        self.word_counts.update(page_counter)
        self.page_word_counts[url] = dict(page_counter)
        self.total_words_processed += len(words)
        
        if not self.quiet:
            print(f"    Found {len(words)} words ({len(set(words))} unique)")
        
        # Extract links for further crawling
        links = self.text_processor.extract_links(html_content, url)
        same_domain_links = {
            link for link in links 
            if URLValidator.is_same_domain(link, url) and link not in self.visited_urls
        }
        
        if not self.quiet:
            if same_domain_links:
                print(f"    Discovered {len(same_domain_links)} new same-domain links:")
                for i, link in enumerate(sorted(same_domain_links)[:5], 1):
                    print(f"       {i}. {link}")
                if len(same_domain_links) > 5:
                    print(f"       ... and {len(same_domain_links) - 5} more")
            else:
                print("    No new same-domain links found")
            
            # Show running totals
            print(f"    Running totals: {len(self.visited_urls)} pages, {len(self.word_counts)} unique words, {self.total_words_processed} total words")
        
        time.sleep(self.delay)
        return same_domain_links
    
    def crawl_website(self, start_url: str) -> None:
        """Crawl entire website starting from given URL."""
        start_url = URLValidator.normalize_url(start_url)
        target_domain = URLValidator.get_domain(start_url)
        
        if not URLValidator.is_valid_url(start_url):
            print(f"Invalid URL: {start_url}")
            return
        
        if not self.quiet:
            print(f"Starting crawl of domain: {target_domain}")
            print(f"Starting URL: {start_url}")
            print(f"Delay between requests: {self.delay}s")
            print(f"{'='*60}")
        else:
            print(f"Starting crawl of {target_domain}")
        
        urls_to_visit = {start_url}
        page_count = 0
        
        while urls_to_visit:
            page_count += 1
            current_url = urls_to_visit.pop()
            new_links = self.crawl_page(current_url, target_domain, page_count, len(urls_to_visit))
            
            # Filter out any links that might have been discovered by other pages while we were processing
            new_unvisited_links = {link for link in new_links if link not in self.visited_urls}
            urls_to_visit.update(new_unvisited_links)
        
        if not self.quiet:
            print(f"\n{'='*60}")
            print(f"Crawl completed!")
            print(f"Pages visited: {len(self.visited_urls)}")
            print(f"Unique words found: {len(self.word_counts)}")
            print(f"Total word occurrences: {sum(self.word_counts.values())}")
            print(f"Domain crawled: {target_domain}")
            
            if self.word_counts:
                print(f"\nTop 10 most common words:")
                for i, (word, count) in enumerate(self.word_counts.most_common(10), 1):
                    print(f"   {i:2}. {word}: {count}")
            
            print(f"\nAll crawled URLs:")
            for i, url in enumerate(sorted(self.visited_urls), 1):
                print(f"   {i:2}. {url}")
        else:
            print(f"\nCrawl completed: {len(self.visited_urls)} pages, {len(self.word_counts)} unique words")


class OutputManager:
    """Handles different output formats."""
    
    @staticmethod
    def save_results(word_counts: Counter, page_word_counts: Dict[str, Dict[str, int]], 
                    output_file: str, visited_urls: Set[str]) -> None:
        """Save results to file in specified format."""
        file_ext = output_file.lower().split('.')[-1]
        
        if file_ext == 'json':
            OutputManager._save_json(word_counts, page_word_counts, output_file, visited_urls)
        elif file_ext == 'csv':
            OutputManager._save_csv(word_counts, output_file)
        else:
            OutputManager._save_txt(word_counts, output_file)
    
    @staticmethod
    def _save_json(word_counts: Counter, page_word_counts: Dict[str, Dict[str, int]], 
                  output_file: str, visited_urls: Set[str]) -> None:
        """Save results as JSON."""
        data = {
            'summary': {
                'total_pages': len(visited_urls),
                'total_unique_words': len(word_counts),
                'total_word_occurrences': sum(word_counts.values())
            },
            'overall_word_counts': dict(word_counts.most_common()),
            'page_word_counts': page_word_counts,
            'visited_urls': list(visited_urls)
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    @staticmethod
    def _save_csv(word_counts: Counter, output_file: str) -> None:
        """Save results as CSV in count,word format (highest count first)."""
        with open(output_file, 'w', encoding='utf-8') as f:
            for word, count in word_counts.most_common():
                f.write(f"{count},{word}\n")
    
    @staticmethod
    def _save_txt(word_counts: Counter, output_file: str) -> None:
        """Save results as plain text in count,word format (highest count first)."""
        with open(output_file, 'w', encoding='utf-8') as f:
            for word, count in word_counts.most_common():
                f.write(f"{count},{word}\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Web Spider Wordlist Generator - Crawl websites and count words"
    )
    parser.add_argument(
        '--url', 
        required=True, 
        help='Target website URL to crawl'
    )
    parser.add_argument(
        '--output', 
        required=True, 
        help='Output file path (supports .json, .csv, .txt)'
    )
    parser.add_argument(
        '--ignore-file', 
        default='ignore_words.txt',
        help='Path to ignore words file (default: ignore_words.txt)'
    )
    parser.add_argument(
        '--delay', 
        type=float, 
        default=1.0,
        help='Delay between requests in seconds (default: 1.0)'
    )
    parser.add_argument(
        '--quiet', 
        action='store_true',
        help='Reduce output verbosity (show only essential progress)'
    )
    
    args = parser.parse_args()
    
    # Initialize components
    ignore_manager = IgnoreListManager(args.ignore_file)
    spider = WebSpider(ignore_manager, args.delay, args.quiet)
    
    # Crawl website
    spider.crawl_website(args.url)
    
    # Save results
    OutputManager.save_results(
        spider.word_counts, 
        spider.page_word_counts, 
        args.output,
        spider.visited_urls
    )
    
    print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()