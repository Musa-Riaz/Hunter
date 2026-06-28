import asyncio
import sys
import random
import time
import re
import httpx
from fastapi import FastAPI
from playwright.sync_api import sync_playwright
from concurrent.futures import ThreadPoolExecutor
import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI()
executor = ThreadPoolExecutor(max_workers=2)


# ─────────────────────────────────────────
# HELPER: strip HTML tags
# ─────────────────────────────────────────
def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


# ─────────────────────────────────────────
# SOURCE 1: Indeed Pakistan (Playwright)
# ─────────────────────────────────────────
def scrape_indeed(keyword: str, location: str = "Pakistan", browser_context=None):
    jobs = []
    query = keyword.replace(" ", "+")
    loc = location.replace(" ", "+")
    url = f"https://pk.indeed.com/jobs?q={query}&l={loc}&sort=date"
    print(f"Indeed: {url}")

    page = browser_context.new_page()
    try:
        page.goto(url, wait_until="load", timeout=30000)
        time.sleep(3)

        cards = page.query_selector_all("div.job_seen_beacon")
        print(f"Indeed cards found: {len(cards)}")

        for card in cards[:15]:
            try:
                # exact selectors from your HTML
                title_el = card.query_selector("h3.jobTitle a span")
                company_el = card.query_selector("span[data-testid='company-name']")
                location_el = card.query_selector("div[data-testid='text-location']")
                link_el = card.query_selector("h3.jobTitle a")
                salary_el = card.query_selector("span.css-zydy3i")

                title = title_el.inner_text().strip() if title_el else ""
                company = company_el.inner_text().strip() if company_el else ""
                loc_text = location_el.inner_text().strip() if location_el else ""
                salary = salary_el.inner_text().strip() if salary_el else ""
                href = link_el.get_attribute("href") if link_el else ""

                if href and not href.startswith("http"):
                    href = "https://pk.indeed.com" + href

                if not title:
                    continue

                # get description from detail page
                description = ""
                if href:
                    detail_page = browser_context.new_page()
                    try:
                        detail_page.goto(href, wait_until="load", timeout=20000)
                        time.sleep(1)
                        desc_el = detail_page.query_selector("#jobDescriptionText")
                        if desc_el:
                            description = desc_el.inner_text().strip()[:1500]
                    except:
                        pass
                    finally:
                        detail_page.close()
                    time.sleep(random.uniform(1, 2))

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc_text,
                    "type": salary,  # using salary field as type since it's more useful
                    "apply_link": href,
                    "description": description,
                    "source": "indeed.com",
                    "contact_email": "",
                    "company_website": "",
                    "posted_date": ""
                })
                print(f"  Indeed job: {title} @ {company} | {loc_text}")

            except Exception as e:
                print(f"  Indeed card error: {e}")
                continue

    except Exception as e:
        print(f"Indeed error: {e}")
    finally:
        page.close()

    return jobs

# ─────────────────────────────────────────
# SOURCE 2: LinkedIn Jobs (public, no login)
# ─────────────────────────────────────────
def scrape_linkedin(keyword: str, location: str = "Pakistan", browser_context=None):
    jobs = []
    query = keyword.replace(" ", "%20")
    loc = location.replace(" ", "%20")
    url = f"https://www.linkedin.com/jobs/search/?keywords={query}&location={loc}&sortBy=DD&f_TPR=r86400"
    print(f"LinkedIn: {url}")

    page = browser_context.new_page()
    try:
        page.goto(url, wait_until="load", timeout=30000)
        time.sleep(4)
        page.screenshot(path="debug_linkedin.png")
        print(f"LinkedIn title: {page.title()}")

        # scroll to load more cards
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        time.sleep(2)

        cards = page.query_selector_all("div.base-card, li.jobs-search-results__list-item, div.job-search-card")
        print(f"LinkedIn cards found: {len(cards)}")

        for card in cards[:15]:
            try:
                title_el = card.query_selector("h3.base-search-card__title, h3.job-search-card__title")
                company_el = card.query_selector("h4.base-search-card__subtitle, a.job-search-card__company-name")
                location_el = card.query_selector("span.job-search-card__location")
                link_el = card.query_selector("a.base-card__full-link, a.job-search-card__list-date")

                title = title_el.inner_text().strip() if title_el else ""
                company = company_el.inner_text().strip() if company_el else ""
                loc_text = location_el.inner_text().strip() if location_el else ""
                href = link_el.get_attribute("href") if link_el else ""

                if not title:
                    continue

                # get description
                description = ""
                if href:
                    detail_page = browser_context.new_page()
                    try:
                        detail_page.goto(href, wait_until="load", timeout=20000)
                        time.sleep(2)
                        desc_el = detail_page.query_selector("div.description__text, div.show-more-less-html__markup")
                        if desc_el:
                            description = desc_el.inner_text().strip()[:1500]
                    except:
                        pass
                    finally:
                        detail_page.close()
                    time.sleep(random.uniform(1, 2.5))

                jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc_text,
                    "type": "",
                    "apply_link": href,
                    "description": description,
                    "source": "linkedin.com",
                    "contact_email": "",
                    "company_website": "",
                    "posted_date": ""
                })
                print(f"  LinkedIn job: {title} @ {company}")

            except Exception as e:
                print(f"  LinkedIn card error: {e}")
                continue

    except Exception as e:
        print(f"LinkedIn error: {e}")
    finally:
        page.close()

    return jobs


# ─────────────────────────────────────────
# MAIN SCRAPER — shares one browser instance
# ─────────────────────────────────────────
def run_all_scrapers(keyword: str, location: str):
    all_jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # keep visible for now so you can watch what happens
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            java_script_enabled=True,
        )

        # mask automation signals
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            window.chrome = { runtime: {} };
        """)

        print(f"\n=== Scraping Indeed for '{keyword}' ===")
        indeed_jobs = scrape_indeed(keyword, location, context)
        all_jobs.extend(indeed_jobs)
        print(f"Indeed total: {len(indeed_jobs)}")

        time.sleep(2)

        print(f"\n=== Scraping LinkedIn for '{keyword}' ===")
        linkedin_jobs = scrape_linkedin(keyword, location, context)
        all_jobs.extend(linkedin_jobs)
        print(f"LinkedIn total: {len(linkedin_jobs)}")

        time.sleep(2)

        browser.close()

    # deduplicate by link
    seen = set()
    unique = []
    for job in all_jobs:
        if job["apply_link"] and job["apply_link"] not in seen:
            seen.add(job["apply_link"])
            unique.append(job)

    print(f"\n=== Total unique jobs: {len(unique)} ===")
    return unique


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/scrape")
async def scrape(body: dict):
    keyword = body.get("keyword", "full stack developer")
    location = body.get("location", "Pakistan")
    loop = asyncio.get_event_loop()
    jobs = await loop.run_in_executor(executor, run_all_scrapers, keyword, location)
    return {"jobs": jobs, "count": len(jobs)}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)