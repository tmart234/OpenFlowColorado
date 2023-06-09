import requests
import pandas as pd
import io
from io import StringIO
from datetime import datetime, timedelta
import time
import csv

###
# this script finds closest NOAA stations to USGS stations
# it then pulls climate data for NOAA stations
###

noaa_api_token = "ensQWPauKcbtSOmsAvlwRVfWyQjJpbHa"

def lat_lon_to_bbox(lat, lon, miles):
    miles_to_degrees = 1 / 69
    delta = miles * miles_to_degrees
    return lat - delta, lon - delta, lat + delta, lon + delta

def fetch_noaa_temps(noaa_station_id, latitude, longitude):
    temperature_data = {}
    today = datetime.today()
    today_str = today.strftime("%Y-%m-%dT%H:%M:%SZ")
    one_year_ago = today - timedelta(days=365)
    one_year_ago_str = one_year_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
    ncei_search_url = "https://www.ncei.noaa.gov/access/services/search/v1/data"
    bbox = lat_lon_to_bbox(latitude, longitude, 5)
    ncei_search_params = {
        "dataset": "daily-summaries",
        "startDate": one_year_ago_str,
        "endDate": today_str,
        "boundingBox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
        "dataTypes": "TMIN,TMAX",
        "stations": noaa_station_id,
        "format": "csv",
    }
    search_response = requests.get(ncei_search_url, params=ncei_search_params)
    if search_response.status_code == 200 and search_response.text.strip():
        reader = csv.DictReader(io.StringIO(search_response.text))
        for row in reader:
            date_str = row["DATE"]
            min_temp = float(row["TMIN"]) * (9 / 5) + 32  # Convert from Celsius to Fahrenheit
            max_temp = float(row["TMAX"]) * (9 / 5) + 32  # Convert from Celsius to Fahrenheit
            temperature_data[date_str] = (min_temp, max_temp)

    return temperature_data

# Find the distance between 2 lats and longs
# TODO: ideally it's not just a close NOAA station, but also resides in same basin/drainage as the USGS station
def haversine_distance(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2

    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = 6371 * c  # Radius of Earth in kilometers

    return distance

def get_noaa_stations(url, headers):
    offset = 1
    limit = 1000
    stations = []

    while True:
        paginated_url = f"{url}&limit={limit}&offset={offset}"
        response = requests.get(paginated_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        stations.extend(data["results"])

        if data["metadata"]["resultset"]["count"] > offset + limit - 1:
            offset += limit
        else:
            break

    return stations

def save_to_csv(station_id, temperature_data):
    # Convert the temperature data to a pandas DataFrame
    df = pd.DataFrame(temperature_data, columns=["StationID", "Date", "DataType", "Value"])

    # Save the DataFrame to a CSV file
    csv_filename = f"temperature_data_{station_id}.csv"
    df.to_csv(csv_filename, index=False)
    print(f"Saved temperature data for station {station_id} to {csv_filename}")


def fetch_data_with_retry(url, headers, retries=3, delay=5):
    for _ in range(retries):
        response = requests.get(url, headers=headers)
        if response.status_code != 503:
            return response
        time.sleep(delay)
    return None


# TODO: more states besides CO
# states = ["al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi"] 
data_years = 5
# start with a finite amount (free) then expand (paid)
filter_site_ids = ["09058000", "07087050"]
# filter site IDs by int values
filter_site_ids_int = [int(site_id) for site_id in filter_site_ids]
usgs_url = "https://waterdata.usgs.gov/nwis/current?state_cd=co&index_pmcode_STATION_NM=1&index_pmcode_DATETIME=2&index_pmcode_00060=3&index_pmcode_00061=4&group_key=huc_cd&format=sitefile_output&sitefile_output_format=rdb&column_name=site_no&column_name=station_nm&column_name=dec_lat_va&column_name=dec_long_va&column_name=alt_va&column_name=drain_area_va&column_name=contrib_drain_area_va&column_name=rt_bol&column_name=peak_begin_date&column_name=peak_end_date&column_name=gw_begin_date&column_name=gw_end_date&sort_key_2=site_no&html_table_group_key=NONE&rdb_compression=value&list_of_search_criteria=state_cd%2Crealtime_parameter_selection"

response = requests.get(usgs_url)
content = response.text

# Calculate the date range for the last year
end_date = datetime.now()
start_date = end_date - timedelta(days=365)

# Convert the dates to string format
start_date_str = start_date.strftime("%Y-%m-%d")
end_date_str = end_date.strftime("%Y-%m-%d")
# Get today's date as a string
today_str = datetime.now().strftime("%Y-%m-%d")

# Remove comments and the description row from the text
data = '\n'.join([line for line in content.splitlines() if not line.startswith("#") and not line.startswith("5s") and not line.startswith("15s")])

# Read the tab-separated data into a pandas DataFrame
data_frame = pd.read_csv(StringIO(data), sep='\t')

# Create a dictionary with station ID as the key and the other data as values
station_data = {}
for index, row in data_frame.iterrows():
    station_data[row['site_no']] = row.drop('site_no').to_dict()

# Check if any site_id in filter_site_ids is present in station_data
filtered_station_data = {site_id: station_data[site_id] for site_id in filter_site_ids_int if site_id in station_data}
#print(filtered_station_data)

# TODO: check that peak_end_date is not more than 2 years old (inactive) for USGS
# TODO: fix getting closest stations by getting the csv https://github.com/UCHIC/USGS-NIDIS/blob/master/src/Data%20Files/ghcnd-stations.csv and then checking maxdate

# Fetch all available stations in Colorado (FIPS:08)
url = "https://www.ncei.noaa.gov/cdo-web/api/v2/stations?locationid=FIPS:08"
headers = {"token": noaa_api_token}

stations = get_noaa_stations(url, headers=headers)
# Find the nearest station for each site in filtered_station_data
nearest_stations = {}
#print(stations)
# TODO: might need better methods to vouch for quality of a NOAA station's data and choose near but best quality

for site_id, site_data in filtered_station_data.items():
    nearest_station = None
    nearest_distance = None
    # site needs readings within the last 3 days
    days_ago = datetime.now() - timedelta(days=3)

    for station in stations:
        station_latitude = station["latitude"]
        station_longitude = station["longitude"]

        temp_distance = haversine_distance(site_data["dec_lat_va"], site_data["dec_long_va"], station_latitude, station_longitude)
        station_maxdate = datetime.strptime(station["maxdate"], "%Y-%m-%d")
        # Global Historical Climatology Network - Daily
        if (nearest_distance == None or temp_distance < nearest_distance) and station_maxdate >= days_ago and "GHCND:" in station["id"]:
            temperature_data = fetch_noaa_temps(station['id'], site_data['dec_lat_va'], site_data['dec_long_va'])
            if temperature_data:
                nearest_distance = temp_distance
                nearest_station = station
                most_recent_maxdate = station_maxdate

    print(f"Nearest station for Site ID {site_id}: {nearest_station['id']}, latitude: {nearest_station['latitude']}, longitude: {nearest_station['longitude']}")

    # Update filtered_station_data with the nearest NOAA station data
    site_data["nearest_station"] = nearest_station
    site_data["temperature_data"] = temperature_data