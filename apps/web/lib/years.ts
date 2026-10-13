/** Years to pick from, newest first: a few years ahead (expected graduation) down to 1980
 *  (people who entered university in the 1980s answer too). */
export const OLDEST_YEAR = 1980;
const NEWEST_YEAR = new Date().getFullYear() + 4;
export const YEARS = Array.from({ length: NEWEST_YEAR - OLDEST_YEAR + 1 }, (_, i) => NEWEST_YEAR - i);
