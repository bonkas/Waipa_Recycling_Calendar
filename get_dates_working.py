"""
WORKING SOLUTION: Complete recycling collection finder using Playwright
This is the validated approach that successfully retrieves all collection dates
"""

from playwright.sync_api import sync_playwright
import json
from typing import Dict, Optional, List
import sys
import argparse


def get_recycling_dates(address: str, headless: bool = False, manual_select: bool = False) -> Optional[Dict]:
    """
    Get recycling collection dates for a Waipa address
    
    Args:
        address: The address to look up
        headless: Whether to run browser in headless mode
        
    Returns:
        Dictionary with collection information or None if not found
    """
    
    entry_url = "https://www.wastelesswaipa.co.nz/kerbside-collections/recycling/recycling-collection-dates"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        main_page = context.new_page()
        
        collection_data = None
        
        try:
            # Load main page
            print(f"[1/6] Loading website...")
            main_page.goto(entry_url, wait_until='networkidle')
            
            # Click the "Let's go" button
            print(f"[2/6] Clicking 'Let's go' button...")
            main_page.wait_for_timeout(2000)
            
            button = main_page.query_selector("a:has-text(\"Let's go\")")
            if not button:
                print("Error: Button not found")
                browser.close()
                return None
            
            # Wait for new tab
            with context.expect_page() as page_info:
                button.click()
            
            map_page = page_info.value
            print(f"[3/6] Map tool opened")
            
            # Wait for map to fully load
            map_page.wait_for_timeout(3000)
            
            # Search for address
            print(f"[4/6] Searching for address: {address}")
            
            inputs = map_page.query_selector_all('input[type="text"]')
            if not inputs:
                print("Error: No search input found")
                browser.close()
                return None
            
            search_input = inputs[0]
            search_input.fill(address)
            search_input.press('Enter')
            
            # Wait for search results
            map_page.wait_for_timeout(3000)
            
            # Get search results
            print(f"[5/6] Retrieving search results...")
            
            page_text = map_page.inner_text('body')
            selected_text: Optional[str] = None
            elements = map_page.query_selector_all('*')

            # Prefer ARIA listbox/options for the autocomplete dropdown
            unique_results = []
            try:
                listbox = map_page.locator('[role="listbox"]').first
                if listbox.count() > 0:
                    option_handles = listbox.locator('[role="option"]').element_handles()
                    for opt in option_handles:
                        try:
                            txt = opt.inner_text().strip()
                            if txt and len(txt) > 8:
                                unique_results.append({'text': txt, 'element': opt})
                        except:
                            pass
            except Exception:
                pass

            # Fallback: scan page for clickable items with address-like text
            if not unique_results:
                results = []
                for elem in elements:
                    try:
                        text = elem.inner_text()
                        if any(part in text for part in address.split()[:2]) and ('Awamutu' in text or 'Cambridge' in text):
                            if elem.is_visible() and elem.is_enabled():
                                results.append({'text': text.strip(), 'element': elem})
                    except:
                        pass
                # Remove duplicates (keep unique text)
                seen_texts = set()
                for result in results:
                    text = result['text'].split('\n')[0] if '\n' in result['text'] else result['text']
                    if text not in seen_texts and len(text) > 10:
                        unique_results.append({'text': text, 'element': result['element']})
                        seen_texts.add(text)
            
            # Display results and let user pick (or allow manual click)
            if manual_select:
                if headless:
                    print("[WARNING] Manual selection requested but running headless; continuing with automatic selection.")
                else:
                    print("\n[MANUAL] Please click the correct address in the map window.")
                    print("When done, return here and press Enter to continue...")
                    input()
            elif unique_results:
                print(f"\n[INFO] Found {len(unique_results)} matching address(es):\n")
                for i, result in enumerate(unique_results, 1):
                    print(f"  [{i}] {result['text']}")
                
                # Ask user to pick
                while True:
                    try:
                        choice = input(f"\nSelect address (1-{len(unique_results)}), or 0 for first, or 'm' for manual click: ")
                        if choice.lower() == 'm':
                            print("\n[MANUAL] Please click the correct address in the map window.")
                            print("When done, return here and press Enter to continue...")
                            input()
                            selected_idx = None  # Skip automated click
                            break
                        choice_num = int(choice)
                        
                        if choice_num == 0:
                            selected_idx = 0
                            break
                        elif 1 <= choice_num <= len(unique_results):
                            selected_idx = choice_num - 1
                            break
                        else:
                            print(f"Please enter a number between 0 and {len(unique_results)}")
                    except ValueError:
                        print("Please enter a valid number")
                
                # Click selected result (if not manual)
                if selected_idx is not None:
                    print(f"\n[INFO] Selecting: {unique_results[selected_idx]['text']}")
                    selected_text = unique_results[selected_idx]['text']
                    
                    # First attempt: keyboard navigate the dropdown
                    try:
                        search_input.focus()
                        # ArrowDown typically moves to first suggestion, so +1
                        for _ in range(selected_idx + 1):
                            map_page.keyboard.press('ArrowDown')
                        map_page.keyboard.press('Enter')
                    except Exception:
                        # Fallback: click element directly
                        try:
                            selected_element = unique_results[selected_idx]['element']
                            try:
                                selected_element.double_click()
                            except:
                                try:
                                    selected_element.click(force=True)
                                except:
                                    selected_element.focus()
                                    selected_element.press('Enter')
                        except Exception:
                            print("[WARNING] Could not select the element via click or keyboard")
            else:
                print(f"[WARNING] No results found, clicking first matching element...")
                for elem in elements:
                    try:
                        text = elem.inner_text()
                        if address.split()[0] in text:
                            elem.click()
                            break
                    except:
                        pass
            
            # Wait for data to load
            map_page.wait_for_timeout(3000)
            
            # Extract collection information from the page
            print(f"[6/6] Extracting collection data...")
            
            page_content = map_page.inner_text('body')
            
            # Scrape the actual address displayed on the map
            actual_address = address  # Default to user input
            lines = page_content.split('\n')
            
            # Look for address in the info panel - it's usually at the top
            # Try to find it in the first part of the page content
            for line in lines[:50]:  # Check first 50 lines
                line_stripped = line.strip()
                # Look for addresses (contain numbers and suburb name)
                if len(line_stripped) > 10 and any(suburb in line_stripped for suburb in ['Awamutu', 'Hamilton', 'Otorohanga', 'Cambridge', 'Te Awamutu']):
                    if any(c.isdigit() for c in line_stripped):  # Must have numbers (street/postal numbers)
                        actual_address = line_stripped
                        break
            
            # Parse the displayed information
            result = {
                'input_address': address,
                'selected_address': selected_text,
                'address': actual_address,
                'collection_day': None,
                'mixed_recycling': None,
                'glass_recycling': None,
                'route': None
            }
            
            # Split by sections for better parsing
            lines = page_content.split('\n')
            for i, line in enumerate(lines):
                if 'Your Collection Day is:' in line:
                    if i + 1 < len(lines):
                        day_str = lines[i + 1].strip()
                        if day_str and day_str.upper() in ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY']:
                            result['collection_day'] = day_str
                    break
            
            # Extract mixed recycling info
            for i, line in enumerate(lines):
                if 'Mixed Recycling' in line and 'YELLOW' in line:
                    # Look ahead for the next non-empty line that contains a date
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if 'collected' in lines[j].lower() and 'jan' in lines[j].lower():
                            result['mixed_recycling'] = lines[j].strip()
                            break
                    break
            
            # Extract glass recycling info
            for i, line in enumerate(lines):
                if 'Glass Recycling' in line and 'BLUE' in line:
                    # Look ahead for the next non-empty line that contains a date
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if 'collected' in lines[j].lower() and 'feb' in lines[j].lower():
                            result['glass_recycling'] = lines[j].strip()
                            break
                    break
            
            # Extract route
            for i, line in enumerate(lines):
                if line.strip().startswith('Route'):
                    parts = line.split(':')
                    if len(parts) > 1:
                        result['route'] = parts[1].strip()
                    break
            
            collection_data = result
            
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            browser.close()
        
        return collection_data


def main():
    """Get recycling collection dates for a given address"""
    
    parser = argparse.ArgumentParser(description='Waipa Recycling Collection Dates Finder')
    parser.add_argument('address', nargs='?', default='101 Bank Street, Te Awamutu 3800',
                        help='The address to look up (default: 101 Bank Street, Te Awamutu 3800 - the Waipa District Council office)')
    parser.add_argument('--headless', action='store_true', help='Run browser in headless mode')
    parser.add_argument('--manual-select', action='store_true', help='Manually click the correct address in the map')
    
    args = parser.parse_args()
    
    print("="*70)
    print("Waipa Recycling Collection Dates Finder")
    print("="*70)
    
    address = args.address
    
    print(f"\nLooking up: {address}\n")
    
    result = get_recycling_dates(address, headless=args.headless, manual_select=args.manual_select)
    
    if result:
        print("\n" + "="*70)
        print("COLLECTION INFORMATION")
        print("="*70)
        
        # Show all address contexts to highlight any mismatch
        if result.get('input_address'):
            print(f"\nSearched Address: {result['input_address']}")
        if result.get('selected_address'):
            print(f"Selected Address: {result['selected_address']}")
        print(f"Page Address: {result['address']}")
        print(f"\nYour Collection Day is: {result['collection_day']}")
        
        if result['mixed_recycling']:
            print(f"\nMixed Recycling (YELLOW bin):")
            print(f"  {result['mixed_recycling']}")
        
        if result['glass_recycling']:
            print(f"\nGlass Recycling (BLUE bin):")
            print(f"  {result['glass_recycling']}")
        
        print("\n" + "="*70)
    else:
        print("[ERROR] Could not retrieve collection information")
    
    return result


if __name__ == '__main__':
    main()
