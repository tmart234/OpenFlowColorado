import requests
import io
from datetime import datetime, timedelta
import time
import csv
import math
import re
import json

# given a coordinate, find closest NOAA station
# tests a single NOAA station to get 1 year of historical temperature data
# handle errors accordingly if data is not available
# NOAA station may not have current daily data so script wiil find one with recent data

Country = 'US'
noaa_api_token = "ensQWPauKcbtSOmsAvlwRVfWyQjJpbHa"
headers = {"token": noaa_api_token}
fileds = ["TMIN","TMAX"]

def find_station_with_recent_data(sorted_stations, noaa_api_token, fields):
    # TODO: also check for data coverage greater than 0.9
    current_year = datetime.now().year
    one_month_ago = datetime(current_year, datetime.now().month, 1) - timedelta(days=1)
    #print(f"One month ago is: {one_month_ago.month} and current year is {current_year}")

    for station_id in sorted_stations:
        metadata = get_station_metadata(station_id, noaa_api_token)
        if metadata:
            maxdate_str = metadata.get("maxdate")
            maxdate = datetime.strptime(maxdate_str, "%Y-%m-%d")
            print(f"Station ID: {station_id} has a month of: {maxdate.month} and year {maxdate.year}")

            # check that the station has valid data for the last year and last month
            if maxdate.year == current_year and maxdate.month >= one_month_ago.month:
                bool_value = check_fields(fields, station_id)
                if bool_value:
                    return station_id
    return None

def check_fields(fields, id, start_str, end_date_str):
    url = "https://www.ncei.noaa.gov/access/services/search/v1/data"
    ncei_search_params = {
        "dataset": "daily-summaries",
        "startDate": start_str + "T00:00:00",
        "endDate": end_date_str + "T00:00:00",
        "dataTypes": ",".join(fields),
        "stations": id,
    }

    # Encode the parameters without encoding the colons in the datetime strings
    encoded_params = [
        f"{k}={','.join(v) if isinstance(v, list) else v}" for k, v in ncei_search_params.items()
    ]

    # Join the encoded parameters with '&' and add them to the URL
    request_url = url + "?" + "&".join(encoded_params)
    print(f"checking fields for: {request_url}")

    search_response = get_data(request_url)
    # Assuming search_response is a JSON string
    search_response_json = json.loads(search_response)
    data_types = search_response_json.get("dataTypes", {}).get("buckets", [])
    # Check if the desired fields are in the response
    response_fields = {data_type["key"] for data_type in data_types}
    if all(field in response_fields for field in fields):
        return True
    print("bad fields... checking next ID")
    return False

def get_data(url, headers=None, max_retries=3):
    retries = 0
    while retries < max_retries:
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                if response.text:
                    return response.text
                else:
                    print("Response status code is 200, but no data received.")
                    return None
            elif response.status_code == 503:  # Retry on 503 errors
                retries += 1
                print(f"Received a 503 error. Retrying... ({retries}/{max_retries})")
                time.sleep(0.3)  # Sleep for 0.3 seconds before retrying
            else:
                print(f"Request failed with status code {response.status_code}.")
                return None
        except requests.exceptions.RequestException as e:
            print(f"An error occurred: {e}")
            return None
    print(f"Exceeded maximum retries ({max_retries}) for URL {url}.")
    return None

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth's radius in kilometers
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat, dlon = lat2_rad - lat1_rad, lon2_rad - lon1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def find_closest_ghcnd_station(latitude, longitude, noaa_api_token, fields):
    # store all US stations in us_stations
    stations_url = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
    response_text = get_data(stations_url)
    if response_text is not None:
        us_stations = []
        for line in response_text.splitlines():
            if line.startswith(Country):
                us_stations.append(line)
    else:
        print("Failed to fetch GHCND stations.")
        us_stations = None

    if us_stations is not None:
        print("US stations found!!")
        #print(us_stations)
    else:
        print("No US stations found. Exiting....")
        exit()

    closest_station = None

     # regex pattern for stations
    pattern = re.compile(r"US[a-zA-Z0-9_]{6}\d+")

    stations_with_distances = []

    for line in us_stations:
        station_id, lat, lon, *_ = line.split()

        if not pattern.match(station_id):
            #print(f"bad match for: {station_id}")
            continue

        lat, lon = float(lat), float(lon)
        distance = haversine_distance(latitude, longitude, lat, lon)
        stations_with_distances.append((station_id, distance))

    # Sort stations by distance and limit the list to 15 items
    # increase size if this part is failing
    sorted_stations = sorted(stations_with_distances, key=lambda x: x[1])[:15]
    print(f"Close station list: {sorted_stations}")

    if not sorted_stations:
        print("No stations found within the distance limit. Exiting...")
        return None

    closest_station = None
    closest_station = find_station_with_recent_data(sorted_stations, noaa_api_token, fields)
    if closest_station:
        print(f"The closest station with recent data and valid fields is {closest_station}.")
    else:
        print("No station found with recent data and valid fields.")
    return closest_station

def get_station_metadata(noaa_station_id, noaa_api_token):
    if not noaa_station_id.startswith("GHCND:"):
        noaa_station_id = "GHCND:" + noaa_station_id
    cdo_api_url = "https://www.ncei.noaa.gov/cdo-web/api/v2/stations/"
    time.sleep(0.3)  # Sleep for 0.3 seconds to avoid hitting the rate limit

    metadata_url = f"{cdo_api_url}{noaa_station_id}"
    metadata_response = get_data(metadata_url, headers=headers)

    if metadata_response:
        metadata = json.loads(metadata_response)
        if not metadata:
            print(f"No metadata found for URL: {metadata}")
            return None
        print(f"{noaa_station_id} metadata: {metadata}")
        return metadata
    else:
        print("No metadata received.")
        return None


def fetch_temperature_data(nearest_station_id, noaa_api_token):
    temperature_data = {}
    
    # Get station metadata
    metadata = get_station_metadata(nearest_station_id, noaa_api_token)
    print(metadata)
    
    if not metadata:
        print("Failed to fetch station metadata.")
        return temperature_data

    # Use the end date on record if available
    end_date_str = metadata.get("maxdate") if metadata.get("maxdate") else datetime.today().strftime("%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    one_year_ago = end_date - timedelta(days=365)
    one_year_ago_str = one_year_ago.strftime("%Y-%m-%d")

    ncei_search_url = "https://www.ncei.noaa.gov/access/services/data/v1"
    ncei_search_params = {
        "dataset": "daily-summaries",
        "startDate": one_year_ago_str + "T00:00:00",
        "endDate": end_date_str + "T00:00:00",
        "dataTypes": "TMIN,TMAX",
        "stations": nearest_station_id,
    }

    # Encode the parameters without encoding the colons in the datetime strings
    encoded_params = [
        f"{k}={','.join(v) if isinstance(v, list) else v}" for k, v in ncei_search_params.items()
    ]
    # Join the encoded parameters with '&' and add them to the URL
    request_url = ncei_search_url + "?" + "&".join(encoded_params)
    print("Temperature data URL:", request_url)

    response_text = get_data(request_url, headers=headers)

    if response_text:
        print(response_text)
        reader = csv.DictReader(io.StringIO(response_text))
        for row in reader:
            date_str = row["DATE"]
            # temperature values are given in tenths of degrees Celsius. In this case, we need to divide the values by 10 
            min_temp = (float(row["TMIN"])/10) * (9 / 5) + 32  # Convert from Celsius to Fahrenheit
            max_temp = (float(row["TMAX"])/10) * (9 / 5) + 32  # Convert from Celsius to Fahrenheit
            temperature_data[date_str] = (min_temp, max_temp)
    else:
        print("Could not get temperature data!!")

    csv_string = io.StringIO()
    fieldnames = ["DATE", "TMIN", "TMAX"]
    writer = csv.DictWriter(csv_string, fieldnames=fieldnames)

    writer.writeheader()
    for date_str, (min_temp, max_temp) in temperature_data.items():
        writer.writerow({"DATE": date_str, "TMIN": min_temp, "TMAX": max_temp})

    return csv_string.getvalue()

def main(latitude, longitude, noaa_api_token):
    nearest_station_id = find_closest_ghcnd_station(latitude, longitude, noaa_api_token, fileds)
    #nearest_station_id = "USC00058501"
    if nearest_station_id:
        print("Nearest station ID with good data:", nearest_station_id)
        temperature_data = fetch_temperature_data(nearest_station_id, noaa_api_token)
        return nearest_station_id, temperature_data
    else:
        print("No station found near the specified location.")
        return None


if __name__ == "__main__":
    latitude = 39.045002
    longitude = -106.257903
    id, temp_data = main(latitude, longitude, noaa_api_token)
    # save csv file locally
    with open(f"{id}_temperature_data.csv", "w") as csv_file:
        csv_file.write(temp_data)