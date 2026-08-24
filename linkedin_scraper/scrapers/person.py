"""Person/Profile scraper for LinkedIn."""

import logging
import re
from typing import Optional
from urllib.parse import urljoin
from playwright.async_api import Page

from .base import BaseScraper
from ..models import Person, Experience, Education, Accomplishment, Interest, Contact
from ..callbacks import ProgressCallback, SilentCallback
from ..core.exceptions import ScrapingError

logger = logging.getLogger(__name__)


class PersonScraper(BaseScraper):
    """Async scraper for LinkedIn person profiles."""

    def __init__(self, page: Page, callback: Optional[ProgressCallback] = None):
        """
        Initialize person scraper.

        Args:
            page: Playwright page object
            callback: Progress callback
        """
        super().__init__(page, callback)

    async def scrape(self, linkedin_url: str) -> Person:
        """
        Scrape a LinkedIn person profile.

        Args:
            linkedin_url: LinkedIn profile URL

        Returns:
            Person object with all scraped data

        Raises:
            AuthenticationError: If not logged in
            ScrapingError: If scraping fails
        """
        await self.callback.on_start("person", linkedin_url)

        try:
            # Navigate to profile first (this loads the page with our session)
            await self.navigate_and_wait(linkedin_url)
            await self.callback.on_progress("Navigated to profile", 10)

            # Now check if logged in
            await self.ensure_logged_in()

            # Wait for main content
            await self.page.wait_for_selector("main", timeout=10000)
            await self.wait_and_focus(1)

            # Get name and location
            name, location = await self._get_name_and_location()
            await self.callback.on_progress(f"Got name: {name}", 20)

            # Check open to work
            open_to_work = await self._check_open_to_work()

            # Get about
            about = await self._get_about()
            await self.callback.on_progress("Got about section", 30)

            # Scroll to load lazy-rendered sections (Experience, Education use LazyColumn)
            await self.scroll_page_to_half()
            await self.wait_and_focus(1.0)
            await self.scroll_page_to_bottom(pause_time=1.0, max_scrolls=5)
            await self.wait_and_focus(1.0)

            # Get experiences
            experiences = await self._get_experiences(linkedin_url)
            await self.callback.on_progress(f"Got {len(experiences)} experiences", 60)

            educations = await self._get_educations(linkedin_url)
            await self.callback.on_progress(f"Got {len(educations)} educations", 50)

            interests = await self._get_interests(linkedin_url)
            await self.callback.on_progress(f"Got {len(interests)} interests", 65)

            accomplishments = await self._get_accomplishments(linkedin_url)
            await self.callback.on_progress(
                f"Got {len(accomplishments)} accomplishments", 85
            )

            skills = await self._get_skills(linkedin_url)
            await self.callback.on_progress(f"Got {len(skills)} skills", 90)

            contacts = await self._get_contacts(linkedin_url)
            await self.callback.on_progress(f"Got {len(contacts)} contacts", 95)

            person = Person(
                linkedin_url=linkedin_url,
                name=name,
                location=location,
                about=about,
                open_to_work=open_to_work,
                experiences=experiences,
                educations=educations,
                interests=interests,
                accomplishments=accomplishments,
                skills=skills,
                contacts=contacts,
            )

            await self.callback.on_progress("Scraping complete", 100)
            await self.callback.on_complete("person", person)

            return person

        except Exception as e:
            await self.callback.on_error(e)
            raise ScrapingError(f"Failed to scrape person profile: {e}")

    async def _get_name_and_location(self) -> tuple[str, Optional[str]]:
        """Extract name and location from profile."""
        try:
            # Name is in the first h2 in main that has no componentkey (section h2s have it)
            name = await self.safe_extract_text("main h2:not([componentkey])", default="Unknown")

            # Location: find the p element in the top card that looks like a location
            location = await self.page.evaluate("""() => {
                const topCard = document.querySelector('[componentkey$="Topcard"]');
                if (!topCard) return null;
                const ps = [...topCard.querySelectorAll('p')];
                // Location typically has a comma and isn't a pronoun or degree indicator
                for (const p of ps) {
                    const t = p.textContent.trim();
                    if (t.includes(',') && !t.includes('·') && t.length < 100) return t;
                }
                return null;
            }""")
            return name, location if location else None
        except Exception as e:
            logger.warning(f"Error getting name/location: {e}")
            return "Unknown", None

    async def _check_open_to_work(self) -> bool:
        """Check if profile has open to work badge."""
        try:
            # Look for open to work ring/label in the top card
            count = await self.page.locator(
                '[aria-label*="open to work" i], [title*="open to work" i], '
                'img[alt*="open to work" i]'
            ).count()
            return count > 0
        except:
            return False

    async def _get_about(self) -> Optional[str]:
        """Extract about section."""
        try:
            # Find the About h2 and get the expandable text box near it
            about_h2 = self.page.locator('h2[componentkey*="About"], h2:has-text("About")').first
            if await about_h2.count() > 0:
                # The expandable text box is a sibling or nearby element
                section = about_h2.locator('xpath=ancestor::*[2]')
                if await section.count() > 0:
                    box = section.locator('[data-testid="expandable-text-box"]').first
                    if await box.count() > 0:
                        text = await box.inner_text()
                        return text.strip() if text else None

            # Fallback: first expandable-text-box in main (usually About)
            boxes = await self.page.locator('main [data-testid="expandable-text-box"]').all()
            for box in boxes:
                text = await box.inner_text()
                if text and len(text.strip()) > 20:
                    return text.strip()

            return None
        except Exception as e:
            logger.debug(f"Error getting about section: {e}")
            return None

    async def _get_experiences(self, base_url: str) -> list[Experience]:
        """Extract experiences from the main profile page Experience section."""
        experiences = []

        try:
            # Use data-testid to find the experience section (stable across LinkedIn redesigns)
            exp_section = self.page.locator('[data-testid*="ExperienceTopLevel"]').first
            if await exp_section.count() > 0:
                items = await exp_section.locator('[componentkey^="entity-collection-item"]').all()
                for item in items:
                    try:
                        exp = await self._parse_main_page_experience(item)
                        if exp:
                            experiences.append(exp)
                    except Exception as e:
                        logger.debug(f"Error parsing experience from main page: {e}")
                        continue

            if not experiences:
                exp_url = urljoin(base_url, "details/experience")
                await self.navigate_and_wait(exp_url)
                await self.page.wait_for_selector("main", timeout=10000)
                await self.wait_and_focus(1.5)
                await self.scroll_page_to_half()
                await self.scroll_page_to_bottom(pause_time=0.5, max_scrolls=5)

                items = await self.page.locator(
                    'main [componentkey^="entity-collection-item"]'
                ).all()
                if not items:
                    items = await self.page.locator('main ul > li, main ol > li').all()

                for item in items:
                    try:
                        result = await self._parse_experience_item(item)
                        if result:
                            if isinstance(result, list):
                                experiences.extend(result)
                            else:
                                experiences.append(result)
                    except Exception as e:
                        logger.debug(f"Error parsing experience item: {e}")
                        continue

        except Exception as e:
            logger.warning(
                f"Error getting experiences: {e}. The experience section may not be available or the page structure has changed."
            )

        return experiences
    
    async def _parse_main_page_experience(self, item) -> Optional[Experience]:
        """Parse experience from main profile page entity-collection-item."""
        try:
            links = await item.locator('a').all()
            company_url = await links[0].get_attribute('href') if links else None

            text = await item.inner_text()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if len(lines) < 2:
                return None

            # Detect grouped company card: line[1] starts with an employment type or duration
            # (e.g. "Full-time · 4 yrs 11 mos") vs single-role where line[1] = "Company · Type"
            employment_types = {"Full-time", "Part-time", "Contract", "Freelance", "Internship",
                                "Seasonal", "Self-employed", "Apprenticeship"}
            first_segment = lines[1].split("·")[0].strip() if len(lines) >= 2 else ""
            is_grouped = first_segment in employment_types or (
                len(lines) >= 2 and self._is_date_or_duration(lines[1]) and "·" not in lines[1]
            )

            if is_grouped:
                # Grouped: company name is first line, roles follow
                company_name = lines[0]
                # Find first role title (line that's not duration/type)
                role_line = next(
                    (l for l in lines[2:] if not self._is_date_or_duration(l) and "·" not in l),
                    None,
                )
                date_line = next((l for l in lines[2:] if self._is_date_or_duration(l)), "")
                from_date, to_date, duration = self._parse_work_times(date_line)
                employment_type = first_segment if first_segment in employment_types else None
                return Experience(
                    position_title=role_line or "",
                    institution_name=company_name,
                    linkedin_url=company_url,
                    from_date=from_date,
                    to_date=to_date,
                    duration=duration,
                    location=None,
                    description=None,
                    employment_type=employment_type,
                )
            else:
                # Single role: title · company · dates · location
                position_title = lines[0]
                company_parts = lines[1].split("·")
                company_name = company_parts[0].strip() if "·" in lines[1] else lines[1]
                employment_type = (
                    company_parts[1].strip()
                    if len(company_parts) > 1 and company_parts[1].strip() in employment_types
                    else None
                )
                date_line = next((l for l in lines[2:] if self._is_date_or_duration(l)), "")
                location = next(
                    (l for l in lines[2:] if not self._is_date_or_duration(l) and "·" not in l),
                    None,
                )
                from_date, to_date, duration = self._parse_work_times(date_line)
                return Experience(
                    position_title=position_title,
                    institution_name=company_name,
                    linkedin_url=company_url,
                    from_date=from_date,
                    to_date=to_date,
                    duration=duration,
                    location=location,
                    description=None,
                    employment_type=employment_type,
                )

        except Exception as e:
            logger.debug(f"Error parsing main page experience: {e}")
            return None

    def _is_date_or_duration(self, text: str) -> bool:
        """Check if text looks like a date range or duration."""
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        has_month = any(m in text for m in months)
        has_year = any(c.isdigit() for c in text)
        has_present = "Present" in text
        has_duration = "yr" in text or "mo" in text
        return (has_month and has_year) or has_present or has_duration
    
    async def _extract_unique_texts_from_element(self, element) -> list[str]:
        """Extract unique text content from nested elements, avoiding duplicates from parent/child overlap."""
        text_elements = await element.locator('span[aria-hidden="true"], div > span').all()
        
        if not text_elements:
            text_elements = await element.locator('span, div').all()
        
        seen_texts = set()
        unique_texts = []
        
        for el in text_elements:
            text = await el.text_content()
            if text and text.strip():
                text = text.strip()
                if text not in seen_texts and len(text) < 200 and not any(text in t or t in text for t in seen_texts if len(t) > 3):
                    seen_texts.add(text)
                    unique_texts.append(text)
        
        return unique_texts

    async def _parse_experience_item(self, item):
        """Parse experience item from detail page using inner_text line parsing."""
        try:
            links = await item.locator('a').all()
            company_url = await links[0].get_attribute('href') if links else None

            return await self._parse_main_page_experience(item)

        except Exception as e:
            logger.debug(f"Error parsing experience: {e}")
            return None

    async def _parse_nested_experience(
        self, item, company_url: str, detail_children
    ) -> list[Experience]:
        """
        Parse nested experience positions (multiple roles at the same company).
        Returns a list of Experience objects.
        """
        experiences = []

        try:
            # Get company name from first detail
            first_detail = detail_children[0]
            nested_elements = await first_detail.locator("> *").all()
            if len(nested_elements) == 0:
                return []

            span_container = nested_elements[0]
            outer_spans = await span_container.locator("> *").all()

            # First span is company name for nested positions
            company_name = ""
            if len(outer_spans) >= 1:
                aria_span = outer_spans[0].locator('span[aria-hidden="true"]').first
                company_name = await aria_span.text_content()

            # Get the nested list from detail_children[1]
            nested_container = detail_children[1].locator(".pvs-list__container").first
            nested_items = await nested_container.locator(
                ".pvs-list__paged-list-item"
            ).all()

            for nested_item in nested_items:
                try:
                    # Each nested item has a link with position details
                    link = nested_item.locator("a").first
                    link_children = await link.locator("> *").all()

                    if len(link_children) == 0:
                        continue

                    # Navigate to get the spans
                    first_child = link_children[0]
                    nested_els = await first_child.locator("> *").all()
                    if len(nested_els) == 0:
                        continue

                    spans_container = nested_els[0]
                    position_spans = await spans_container.locator("> *").all()

                    # Extract position details
                    position_title = ""
                    work_times = ""
                    location = ""

                    if len(position_spans) >= 1:
                        aria_span = (
                            position_spans[0].locator('span[aria-hidden="true"]').first
                        )
                        position_title = await aria_span.text_content()
                    if len(position_spans) >= 2:
                        aria_span = (
                            position_spans[1].locator('span[aria-hidden="true"]').first
                        )
                        work_times = await aria_span.text_content()
                    if len(position_spans) >= 3:
                        aria_span = (
                            position_spans[2].locator('span[aria-hidden="true"]').first
                        )
                        location = await aria_span.text_content()

                    # Parse dates
                    from_date, to_date, duration = self._parse_work_times(work_times)

                    # Get description if available
                    description = ""
                    if len(link_children) > 1:
                        description = await link_children[1].inner_text()

                    experiences.append(
                        Experience(
                            position_title=position_title.strip(),
                            institution_name=company_name.strip(),
                            linkedin_url=company_url,
                            from_date=from_date,
                            to_date=to_date,
                            duration=duration,
                            location=location.strip(),
                            description=description.strip() if description else None,
                        )
                    )

                except Exception as e:
                    logger.debug(f"Error parsing nested position: {e}")
                    continue

        except Exception as e:
            logger.debug(f"Error parsing nested experience: {e}")

        return experiences

    def _parse_work_times(
        self, work_times: str
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Parse work times string into from_date, to_date, duration.

        Examples:
        - "2000 - Present · 26 yrs 1 mo" -> ("2000", "Present", "26 yrs 1 mo")
        - "Jan 2020 - Dec 2022 · 2 yrs" -> ("Jan 2020", "Dec 2022", "2 yrs")
        - "2015 - Present" -> ("2015", "Present", None)
        """
        if not work_times:
            return None, None, None

        try:
            # Split by · to separate date range from duration
            parts = work_times.split("·")
            times = parts[0].strip() if len(parts) > 0 else ""
            duration = parts[1].strip() if len(parts) > 1 else None

            # Parse dates - split by " - " to get from and to
            if " - " in times:
                date_parts = times.split(" - ")
                from_date = date_parts[0].strip()
                to_date = date_parts[1].strip() if len(date_parts) > 1 else ""
            else:
                from_date = times
                to_date = ""

            return from_date, to_date, duration
        except Exception as e:
            logger.debug(f"Error parsing work times '{work_times}': {e}")
            return None, None, None

    async def _get_educations(self, base_url: str) -> list[Education]:
        """Extract educations from the main profile page Education section."""
        educations = []

        try:
            # Use data-testid to find the education section (stable across LinkedIn redesigns)
            edu_section = self.page.locator('[data-testid*="EducationTopLevel"]').first
            if await edu_section.count() > 0:
                items = await edu_section.locator('[componentkey^="entity-collection-item"]').all()
                for item in items:
                    try:
                        edu = await self._parse_main_page_education(item)
                        if edu:
                            educations.append(edu)
                    except Exception as e:
                        logger.debug(f"Error parsing education from main page: {e}")
                        continue

            if not educations:
                edu_url = urljoin(base_url, "details/education")
                await self.navigate_and_wait(edu_url)
                await self.page.wait_for_selector("main", timeout=10000)
                await self.wait_and_focus(2)
                await self.scroll_page_to_half()
                await self.scroll_page_to_bottom(pause_time=0.5, max_scrolls=5)

                items = await self.page.locator(
                    'main [componentkey^="entity-collection-item"]'
                ).all()
                if not items:
                    items = await self.page.locator('main ul > li, main ol > li').all()

                for item in items:
                    try:
                        edu = await self._parse_education_item(item)
                        if edu:
                            educations.append(edu)
                    except Exception as e:
                        logger.debug(f"Error parsing education item: {e}")
                        continue

        except Exception as e:
            logger.warning(
                f"Error getting educations: {e}. The education section may not be publicly visible or the page structure has changed."
            )

        return educations
    
    async def _parse_main_page_education(self, item) -> Optional[Education]:
        """Parse education from main profile page entity-collection-item."""
        try:
            links = await item.locator('a').all()
            institution_url = await links[0].get_attribute('href') if links else None

            text = await item.inner_text()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines:
                return None

            institution_name = lines[0]
            degree = None
            times = ""

            for line in lines[1:]:
                if self._is_date_or_duration(line) or ("–" in line and any(c.isdigit() for c in line)):
                    times = line
                elif not degree and not self._is_date_or_duration(line):
                    degree = line

            from_date, to_date = self._parse_education_times(times)

            return Education(
                institution_name=institution_name,
                degree=degree.strip() if degree else None,
                linkedin_url=institution_url,
                from_date=from_date,
                to_date=to_date,
                description=None,
            )

        except Exception as e:
            logger.debug(f"Error parsing main page education: {e}")
            return None

    async def _parse_education_item(self, item) -> Optional[Education]:
        """Parse a single education item."""
        try:
            links = await item.locator('a, link').all()

            # LinkedIn's current server-driven-UI education page renders
            # institution/degree/dates as separate top-level <p> elements, in
            # that order (a trailing "Skills: ..." <p> may follow - ignored).
            # There are no aria-hidden markers on this page to disambiguate
            # nested wrapper text, so reading top-level <p>s directly is far
            # more reliable than descending into spans/divs.
            p_texts = [t.strip() for t in await item.locator('p').all_text_contents() if t.strip()]
            unique_texts = [t for t in p_texts if not t.lower().startswith("skills:")]

            if len(links) >= 1:
                institution_url = await links[0].get_attribute('href')

                if not unique_texts:
                    detail_link = links[1] if len(links) >= 2 else links[0]
                    unique_texts = await self._extract_unique_texts_from_element(detail_link)

                if unique_texts:
                    institution_name = unique_texts[0]
                    degree = None
                    times = ""
                    
                    if len(unique_texts) == 3:
                        degree = unique_texts[1]
                        times = unique_texts[2]
                    elif len(unique_texts) == 2:
                        second = unique_texts[1]
                        # A bare " - " isn't a reliable date signal - degree
                        # abbreviations use the same separator (e.g. "Bachelor
                        # of Engineering - BE"). A 4-digit year is unambiguous.
                        if re.search(r"\d{4}", second):
                            times = second
                        else:
                            degree = second
                    
                    from_date, to_date = self._parse_education_times(times)
                    
                    return Education(
                        institution_name=institution_name,
                        degree=degree.strip() if degree else None,
                        linkedin_url=institution_url,
                        from_date=from_date,
                        to_date=to_date,
                        description=None,
                    )
            
            entity = item.locator('div[data-view-name="profile-component-entity"]').first
            if await entity.count() == 0:
                return None

            children = await entity.locator("> *").all()
            if len(children) < 2:
                return None

            institution_link = children[0].locator("a").first
            institution_url = await institution_link.get_attribute("href")

            detail_container = children[1]
            detail_children = await detail_container.locator("> *").all()

            if len(detail_children) == 0:
                return None

            first_detail = detail_children[0]
            nested_elements = await first_detail.locator("> *").all()

            if len(nested_elements) == 0:
                return None

            span_container = nested_elements[0]
            outer_spans = await span_container.locator("> *").all()

            institution_name = ""
            degree = None
            times = ""

            if len(outer_spans) >= 1:
                aria_span = outer_spans[0].locator('span[aria-hidden="true"]').first
                institution_name = await aria_span.text_content()

            if len(outer_spans) == 3:
                aria_span = outer_spans[1].locator('span[aria-hidden="true"]').first
                degree = await aria_span.text_content()
                aria_span = outer_spans[2].locator('span[aria-hidden="true"]').first
                times = await aria_span.text_content()
            elif len(outer_spans) == 2:
                aria_span = outer_spans[1].locator('span[aria-hidden="true"]').first
                times = await aria_span.text_content()

            from_date, to_date = self._parse_education_times(times)

            description = ""
            if len(detail_children) > 1:
                description = await detail_children[1].inner_text()

            return Education(
                institution_name=institution_name.strip(),
                degree=degree.strip() if degree else None,
                linkedin_url=institution_url,
                from_date=from_date,
                to_date=to_date,
                description=description.strip() if description else None,
            )

        except Exception as e:
            logger.debug(f"Error parsing education: {e}")
            return None

    def _parse_education_times(self, times: str) -> tuple[Optional[str], Optional[str]]:
        """
        Parse education times string into from_date, to_date.

        Examples:
        - "1973 - 1977" -> ("1973", "1977")
        - "2015" -> ("2015", "2015")
        - "" -> (None, None)
        """
        if not times:
            return None, None

        try:
            # Handle both regular hyphen and en-dash separators
            for sep in [" – ", " - ", "–", "-"]:
                if sep in times:
                    parts = times.split(sep, 1)
                    return parts[0].strip(), parts[1].strip()
            # Single year
            return times.strip(), times.strip()
        except Exception as e:
            logger.debug(f"Error parsing education times '{times}': {e}")
            return None, None

    async def _get_interests(self, base_url: str) -> list[Interest]:
        """Extract interests from the main profile page Interests section with tablist."""
        interests = []

        try:
            interests_heading = self.page.locator('h2:has-text("Interests")').first
            
            if await interests_heading.count() > 0:
                interests_section = interests_heading.locator('xpath=ancestor::*[.//tablist or .//*[@role="tablist"]][1]')
                if await interests_section.count() == 0:
                    interests_section = interests_heading.locator('xpath=ancestor::*[4]')
                
                tabs = await interests_section.locator('[role="tab"], tab').all() if await interests_section.count() > 0 else []
                
                if tabs:
                    for tab in tabs:
                        try:
                            tab_name = await tab.text_content()
                            if not tab_name:
                                continue
                            tab_name = tab_name.strip()
                            category = self._map_interest_tab_to_category(tab_name)

                            await tab.click()
                            await self.wait_and_focus(0.5)

                            tabpanel = interests_section.locator('[role="tabpanel"]').first
                            if await tabpanel.count() > 0:
                                list_items = await tabpanel.locator('li, listitem').all()
                                
                                for item in list_items:
                                    try:
                                        interest = await self._parse_interest_item(item, category)
                                        if interest:
                                            interests.append(interest)
                                    except Exception as e:
                                        logger.debug(f"Error parsing interest item: {e}")
                                        continue
                        except Exception as e:
                            logger.debug(f"Error processing interest tab: {e}")
                            continue
            
            if not interests:
                interests_url = urljoin(base_url, "details/interests/")
                await self.navigate_and_wait(interests_url)
                await self.page.wait_for_selector("main", timeout=10000)
                await self.wait_and_focus(1.5)

                tabs = await self.page.locator('[role="tab"], tab').all()

                if not tabs:
                    logger.debug("No interests tabs found on profile")
                    return interests

                for tab in tabs:
                    try:
                        tab_name = await tab.text_content()
                        if not tab_name:
                            continue
                        tab_name = tab_name.strip()
                        category = self._map_interest_tab_to_category(tab_name)

                        await tab.click()
                        await self.wait_and_focus(0.8)

                        tabpanel = self.page.locator('[role="tabpanel"], tabpanel').first
                        list_items = await tabpanel.locator("li, [data-view-name*='interest'], .pvs-list__paged-list-item, [componentkey]").all()

                        for item in list_items:
                            try:
                                interest = await self._parse_interest_item(item, category)
                                if interest:
                                    interests.append(interest)
                            except Exception as e:
                                logger.debug(f"Error parsing interest item: {e}")
                                continue

                    except Exception as e:
                        logger.debug(f"Error processing interest tab: {e}")
                        continue

        except Exception as e:
            logger.warning(f"Error getting interests: {e}")

        return interests
    
    async def _parse_interest_item(self, item, category: str) -> Optional[Interest]:
        """Parse a single interest item from profile or details page."""
        try:
            link = item.locator("a, link").first
            if await link.count() == 0:
                return None
            href = await link.get_attribute("href")

            unique_texts = await self._extract_unique_texts_from_element(item)
            name = unique_texts[0] if unique_texts else None

            if name and href:
                return Interest(
                    name=name,
                    category=category,
                    linkedin_url=href,
                )
            return None
        except Exception as e:
            logger.debug(f"Error parsing interest: {e}")
            return None

    def _map_interest_tab_to_category(self, tab_name: str) -> str:
        tab_lower = tab_name.lower()
        if "compan" in tab_lower:
            return "company"
        elif "group" in tab_lower:
            return "group"
        elif "school" in tab_lower:
            return "school"
        elif "newsletter" in tab_lower:
            return "newsletter"
        elif "voice" in tab_lower or "influencer" in tab_lower:
            return "influencer"
        else:
            return tab_lower

    async def _get_skills(self, base_url: str) -> list[str]:
        """Extract the Skills section via its details page, following the
        same navigate-to-details-page pattern as _get_accomplishments."""
        skills: list[str] = []

        try:
            section_url = urljoin(base_url, "details/skills/")
            await self.navigate_and_wait(section_url)
            await self.page.wait_for_selector("main", timeout=10000)
            await self.wait_and_focus(1)

            nothing_to_see = await self.page.locator(
                'text="Nothing to see for now"'
            ).count()
            if nothing_to_see > 0:
                return skills

            try:
                # The entity-collection-item cards render asynchronously; without
                # this explicit wait, a slow page can fall through to the broad
                # fallback selector below and pick up unrelated page chrome
                # ("More profiles for you" names, footer links) instead.
                await self.page.wait_for_selector(
                    'main [componentkey^="entity-collection-item"]', timeout=5000
                )
            except Exception:
                pass

            items = await self.page.locator(
                'main [componentkey^="entity-collection-item"]'
            ).all()
            if not items:
                items = await self.page.locator('main li, main [data-view-name], main [componentkey]').all()
            if not items:
                return skills
            items = [i for i in items if await i.text_content() and (await i.text_content()).strip()]

            seen = set()
            for item in items:
                try:
                    entity = item.locator(
                        'div[data-view-name="profile-component-entity"]'
                    ).first
                    if await entity.count() > 0:
                        span = entity.locator('span[aria-hidden="true"]').first
                    else:
                        span = item.locator('span[aria-hidden="true"]').first

                    name = await span.text_content() if await span.count() > 0 else None

                    if not name:
                        # LinkedIn's newer server-driven-UI skills page has no
                        # aria-hidden spans / profile-component-entity wrapper
                        # at all - the skill name is just the item's first <p>
                        # (endorsement/assessment rows follow in a later
                        # role="list" sibling, so they're never picked up here).
                        p_first = item.locator('p').first
                        if await p_first.count() > 0:
                            name = await p_first.text_content()

                    if not name:
                        continue
                    name = name.strip()
                    if not name or len(name) > 200:
                        continue
                    if name not in seen:
                        seen.add(name)
                        skills.append(name)
                except Exception as e:
                    logger.debug(f"Error parsing skill item: {e}")
                    continue

        except Exception as e:
            logger.debug(f"Error getting skills: {e}")

        return skills

    async def _get_accomplishments(self, base_url: str) -> list[Accomplishment]:
        accomplishments = []

        accomplishment_sections = [
            ("certifications", "certification"),
            ("honors", "honor"),
            ("publications", "publication"),
            ("patents", "patent"),
            ("courses", "course"),
            ("projects", "project"),
            ("languages", "language"),
            ("organizations", "organization"),
        ]

        for url_path, category in accomplishment_sections:
            try:
                section_url = urljoin(base_url, f"details/{url_path}/")
                await self.navigate_and_wait(section_url)
                await self.page.wait_for_selector("main", timeout=10000)
                await self.wait_and_focus(1)

                nothing_to_see = await self.page.locator(
                    'text="Nothing to see for now"'
                ).count()
                if nothing_to_see > 0:
                    continue

                items = await self.page.locator(
                    'main [componentkey^="entity-collection-item"]'
                ).all()
                if not items:
                    items = await self.page.locator('main li, main [data-view-name], main [componentkey]').all()
                if not items:
                    continue
                # Filter out empty/nav elements
                items = [i for i in items if await i.text_content() and (await i.text_content()).strip()]

                seen_titles = set()
                for item in items:
                    try:
                        accomplishment = await self._parse_accomplishment_item(
                            item, category
                        )
                        if accomplishment and accomplishment.title not in seen_titles:
                            seen_titles.add(accomplishment.title)
                            accomplishments.append(accomplishment)
                    except Exception as e:
                        logger.debug(f"Error parsing {category} item: {e}")
                        continue

            except Exception as e:
                logger.debug(f"Error getting {category}s: {e}")
                continue

        return accomplishments

    async def _parse_accomplishment_item(
        self, item, category: str
    ) -> Optional[Accomplishment]:
        try:
            entity = item.locator(
                'div[data-view-name="profile-component-entity"]'
            ).first
            if await entity.count() > 0:
                spans = await entity.locator('span[aria-hidden="true"]').all()
            else:
                spans = await item.locator('span[aria-hidden="true"]').all()

            title = ""
            issuer = ""
            issued_date = ""
            credential_id = ""

            for i, span in enumerate(spans[:5]):
                text = await span.text_content()
                if not text:
                    continue
                text = text.strip()

                if len(text) > 500:
                    continue

                if i == 0:
                    title = text
                elif "Issued by" in text:
                    parts = text.split("·")
                    issuer = parts[0].replace("Issued by", "").strip()
                    if len(parts) > 1:
                        issued_date = parts[1].strip()
                elif "Issued " in text and not issued_date:
                    issued_date = text.replace("Issued ", "")
                elif "Credential ID" in text:
                    credential_id = text.replace("Credential ID ", "")
                elif i == 1 and not issuer:
                    issuer = text
                elif (
                    any(
                        month in text
                        for month in [
                            "Jan",
                            "Feb",
                            "Mar",
                            "Apr",
                            "May",
                            "Jun",
                            "Jul",
                            "Aug",
                            "Sep",
                            "Oct",
                            "Nov",
                            "Dec",
                        ]
                    )
                    and not issued_date
                ):
                    if "·" in text:
                        parts = text.split("·")
                        issued_date = parts[0].strip()
                    else:
                        issued_date = text

            link = item.locator('a[href*="credential"], a[href*="verify"]').first
            credential_url = (
                await link.get_attribute("href") if await link.count() > 0 else None
            )

            if not title or len(title) > 200:
                return None

            return Accomplishment(
                category=category,
                title=title,
                issuer=issuer if issuer else None,
                issued_date=issued_date if issued_date else None,
                credential_id=credential_id if credential_id else None,
                credential_url=credential_url,
            )

        except Exception as e:
            logger.debug(f"Error parsing accomplishment: {e}")
            return None

    async def _get_contacts(self, base_url: str) -> list[Contact]:
        """Extract contact info from the contact-info overlay dialog."""
        contacts = []

        try:
            # Navigate to the base profile first, then click the contact info link
            # (direct overlay URL navigation doesn't always open the modal in LinkedIn's SPA)
            await self.navigate_and_wait(base_url)
            await self.page.wait_for_selector("main", timeout=10000)
            await self.wait_and_focus(1)

            contact_link = self.page.locator('a[href*="overlay/contact-info"]').first
            if await contact_link.count() > 0:
                await contact_link.click()
                logger.debug("Clicked contact info link")
            else:
                # Fallback: navigate directly
                contact_url = urljoin(base_url, "overlay/contact-info/")
                await self.page.goto(contact_url, wait_until="domcontentloaded")
                logger.debug("Navigated directly to contact-info overlay URL")

            await self.wait_and_focus(2)

            # Try multiple selectors — LinkedIn has used different modal patterns over time
            dialog = None
            for selector in [
                '[data-test-modal]',
                '.artdeco-modal',
                'dialog',
                '[role="dialog"]',
                '[aria-label*="contact" i]',
            ]:
                loc = self.page.locator(selector).first
                try:
                    await loc.wait_for(state="visible", timeout=3000)
                    dialog = loc
                    logger.debug(f"Contact dialog found with selector: {selector}")
                    break
                except Exception:
                    continue

            if dialog is None:
                all_dialogs = await self.page.locator('[role="dialog"], dialog, .artdeco-modal').all()
                logger.warning(
                    f"Contact info dialog not found on {self.page.url} "
                    f"(tried 5 selectors, found {len(all_dialogs)} dialog-like elements on page)"
                )
                return contacts

            # LinkedIn renders each contact section as a div[componentkey] containing
            # an SVG icon + a div with two <p> tags: first is the label, second is the value.
            section_divs = await dialog.locator('div[componentkey]').all()
            logger.debug(f"Found {len(section_divs)} contact section divs")
            seen = set()

            for section in section_divs:
                try:
                    paragraphs = await section.locator('> div > p, p').all()
                    if len(paragraphs) < 2:
                        continue

                    label_text = (await paragraphs[0].text_content() or "").strip()
                    contact_type = self._map_contact_heading_to_type(label_text)
                    if not contact_type:
                        continue

                    # Check for a link in the value paragraph
                    link = paragraphs[1].locator('a').first
                    if await link.count() > 0:
                        href = await link.get_attribute('href') or ""
                        link_text = (await link.text_content() or "").strip()
                        # Strip LinkedIn safety redirect wrapper
                        if "/safety/go/" in href and "url=" in href:
                            from urllib.parse import urlparse, parse_qs, unquote
                            parsed = urlparse(href)
                            qs = parse_qs(parsed.query)
                            href = unquote(qs.get("url", [link_text])[0])
                        if contact_type == "email" and href.startswith("mailto:"):
                            href = href[len("mailto:"):]
                        value = href if href else link_text

                        # Extract label in parentheses e.g. "(Portfolio)"
                        label = None
                        value_text = (await paragraphs[1].text_content() or "").strip()
                        if "(" in value_text and value_text.endswith(")"):
                            label = value_text[value_text.rfind("(") + 1:-1]

                        key = (contact_type, value)
                        if key not in seen:
                            seen.add(key)
                            contacts.append(Contact(type=contact_type, value=value, label=label))
                    else:
                        # Plain text value (phone, birthday, address, connected-since)
                        value = (await paragraphs[1].text_content() or "").strip()
                        key = (contact_type, value)
                        if value and key not in seen:
                            seen.add(key)
                            contacts.append(Contact(type=contact_type, value=value))

                except Exception as e:
                    logger.debug(f"Error parsing contact section: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Error getting contacts: {e}")

        return contacts
    
    def _map_contact_heading_to_type(self, heading: str) -> Optional[str]:
        """Map contact section heading to contact type."""
        heading = heading.lower()
        if "profile" in heading:
            return "linkedin"
        elif "website" in heading:
            return "website"
        elif "email" in heading:
            return "email"
        elif "phone" in heading:
            return "phone"
        elif "twitter" in heading or "x.com" in heading:
            return "twitter"
        elif "birthday" in heading:
            return "birthday"
        elif "address" in heading:
            return "address"
        elif "connected" in heading:
            return "connected_since"
        return None
