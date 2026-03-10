# Ixigo Stealth Extraction

1. **Verify Results:** Ixigo takes 5-10 seconds to fetch real data. 
   - If you see "No flights found" or a spinning plane immediately, DO NOT stop. 
   - Wait 5 seconds. If results still don't appear, refresh the page ONCE.
   
2. **Human Movement:** To bypass anti-bot, perform one small scroll down (about 300 pixels) and then scroll back to the top. This triggers the lazy-loading of flight cards.

3. **Dismiss Blockers:** Click the 'X' on any "ixigo money" or "Login" popups that block the view.

4. **Extract Data:** Once the vertical list of flight cards appears, extract up to 5 flights:
   - **airline**: Full name (e.g. "IndiGo")
   - **flight_number**: (e.g. "6E-537")
   - **departure**: HH:MM
   - **arrival**: HH:MM
   - **price**: Total integer price in INR
   - **url**: The absolute URL found on the orange "Book" button.

Return ONLY a JSON array.