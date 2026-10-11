// Display switches shared by Map, Compare, data cards and advertiser choices.
// true enables a collected field; false hides it. Unknown fields stay hidden.
// Initial 35 enabled IDs: COLLECTED-20261007.md, rows with 51/51 state presence.
export const indicatorVisibility=Object.freeze({
  '01.01': true, // Population
  '01.02': true, // Age
  '01.03': true, // Sex
  '01.04': true, // Race / ethnicity
  '01.05': true, // Foreign-born population
  '01.06': true, // Country / region of birth
  '01.07': true, // Citizenship
  '01.08': true, // Year / period of immigration
  '02.01': true, // Median household income
  '02.02': true, // Per-capita income
  '02.03': true, // Median rent
  '02.04': true, // Median home value
  '02.05': true, // Mortgage / selected monthly owner costs
  '02.06': true, // Rent as % of income / rent burden
  '02.07': true, // Owner / renter ratio
  '02.08': true, // Poverty
  '02.09': true, // Households earning $200k+
  '02.10': true, // Cost of living / Regional Price Parities
  '03.01': true, // Bachelor's degree
  '03.02': true, // Master's degree
  '03.03': true, // Doctorate
  '03.04': true, // High school attainment
  '03.05': true, // No diploma
  '03.06': true, // Unemployment
  '03.07': false, // Average / mean salary
  '03.08': false, // Employment growth
  '03.09': true, // Work from home share
  '04.01': true, // Murders
  '04.02': true, // Violent crime
  '04.03': true, // Robbery
  '04.04': true, // Aggravated assault
  '04.05': true, // Burglary
  '04.06': true, // Motor vehicle theft
  '04.07': true, // Rape
  '04.08': false, // Homicide
  '04.09': false, // Crime trends
  '05.01': false, // Drug overdose deaths
  '05.02': false, // Opioid deaths
  '05.03': false, // Fentanyl / synthetic opioid deaths
  '05.04': false, // Cocaine deaths
  '05.05': false, // Methamphetamine / psychostimulant deaths
  '05.06': false, // Heroin deaths
  '05.07': false, // Alcohol-related deaths
  '05.08': false, // Suicide
  '05.09': false, // Homicide mortality
  '05.10': false, // Heart disease deaths
  '05.11': false, // Cancer deaths
  '05.12': false, // Accidental deaths
  '05.13': false, // Life-expectancy-related indicators
  '05.14': false, // Obesity rate
  '05.15': false, // Diabetes rate
  '05.16': false, // Physical inactivity rate
  '06.01': false, // Total homeless
  '06.02': false, // Sheltered homeless
  '06.03': false, // Unsheltered homeless
  '06.04': false, // Homeless veterans
  '06.05': false, // Homeless families
  '06.06': false, // Chronically homeless
  '07.01': true, // Adjusted Gross Income (AGI)
  '07.02': false, // High-income taxpayers / returns
  '07.03': false, // Capital gains
  '07.04': false, // Dividends
  '07.05': false, // Taxes / income tax metrics
  '07.06': false, // Millionaires
  '07.07': false, // Billionaires
  '08.01': false, // Price of a dozen eggs
  '08.02': false, // Cup of coffee price
  '08.03': false, // Big Mac / McDonald's meal price
  '08.04': false, // Gasoline price
  '08.05': true, // Electricity price
  '08.06': false, // Beer price
  '08.07': false, // Average consumer debt
  '08.08': false, // Student loan debt
  '08.09': false, // Average health insurance cost
  '09.01': false, // Fast-food restaurants per 10k residents
  '09.02': false, // Access to a grocery store
  '09.03': false, // Farmers' markets per capita
  '09.04': true, // Fitness / recreation centers per capita
  '09.05': false, // Parks / recreation facilities
  '09.06': false, // PM2.5
  '09.07': false, // Ozone
  '10.01': false, // Data centers
  '10.02': false, // Residential water tariff
  '10.03': false, // Private companies valued at $1B+
  '11.01': false, // All-cancer new cases
  '11.02': false, // New HIV diagnoses
  '11.03': false, // Deaths among people younger than 18
});
