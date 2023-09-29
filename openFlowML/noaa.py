import requests
import io
from datetime import datetime, timedelta
import time
import csv
import math
import re
import json
import os

# given a coordinate, find closest NOAA station
# tests a single NOAA station to get 1 year of historical temperature data
# handle errors accordingly if data is not available
# NOAA station may not have current daily data so script wiil find one with recent data

Country = 'US'
noaa_api_token = "ensQWPauKcbtSOmsAvlwRVfWyQjJpbHa"
headers = {"token": noaa_api_token}
fileds = ["TMIN","TMAX"]

def find_station_with_recent_data(sorted_stations, startStr, fields, endStr):
    #print(f"One month ago is: {one_month_ago.month} and current year is {current_year}")
    for station_id in sorted_stations:
        metadata = get_station_metadata(station_id)
        if metadata:
            # check for high data coverage
            if metadata.get("datacoverage") > 0.87:
                maxdate_str = metadata.get("maxdate")
                mindate_str = metadata.get("mindate")
                maxdate = datetime.strptime(maxdate_str, "%Y-%m-%d")
                mindate = datetime.strptime(mindate_str, "%Y-%m-%d")
                print(f"Station ID: {station_id} has a end of: {maxdate} and start of {mindate}")
                # check that the station has valid data for end
                if maxdate >= endStr and mindate <= startStr:
                    bool_value = check_fields(fields, station_id[0], startStr, endStr)
                    if bool_value:
                        return station_id
    return None

def check_fields(fields, id, start_str, end_str):
    url = "https://www.ncei.noaa.gov/access/services/search/v1/data"
    ncei_search_params = {
        "dataset": "daily-summaries",
        "startDate": start_str.strftime("%Y-%m-%d") + "T00:00:00",
        "endDate": end_str.strftime("%Y-%m-%d") + "T00:00:00",
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

def find_closest_ghcnd_station(latitude, longitude, fields, startStr, endStr):
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

    # Sort stations by distance and limit the list to 50 items
    # increase size if this part is failing
    sorted_stations = sorted(stations_with_distances, key=lambda x: x[1])[:50]
    print(f"Close station list: {sorted_stations}")

    if not sorted_stations:
        print("No stations found within the distance limit. Exiting...")
        return None

    closest_station = None
    closest_station = find_station_with_recent_data(sorted_stations, startStr, fields, endStr)
    if closest_station:
        print(f"The closest station with recent data and valid fields is {closest_station}.")
    else:
        print("No station found with recent data and valid fields.")
    return closest_station

def get_station_metadata(noaa_station_id):
    # Check if noaa_station_id is a tuple, and if so, take the first element
    if isinstance(noaa_station_id, tuple):
        noaa_station_id = noaa_station_id[0]
    # Ensure noaa_station_id is a string
    noaa_station_id = str(noaa_station_id)
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
        #print(f"{noaa_station_id} metadata: {metadata}")
        return metadata
    else:
        print("No metadata received.")
        return None


def fetch_temperature_data(nearest_station_id, startStr, endStr):
    temperature_data = {}
    # Convert datetime objects to strings with the desired format
    start_str = startStr.strftime("%Y-%m-%d")
    end_str = endStr.strftime("%Y-%m-%d")
    # Get station metadata
    metadata = get_station_metadata(nearest_station_id)
    print(metadata)
    
    if not metadata:
        print("Failed to fetch station metadata.")
        return temperature_data

    ncei_search_url = "https://www.ncei.noaa.gov/access/services/data/v1"
    ncei_search_params = {
        "dataset": "daily-summaries",
        "startDate": start_str + "T00:00:00",
        "endDate": end_str + "T00:00:00",
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
        # Preprocess the response text to remove extra spaces
        response_text = "\n".join([line.strip().replace('"', '') for line in response_text.splitlines()])
        #print(response_text)
        reader = csv.DictReader(io.StringIO(response_text))
        for row in reader:
            date_str = row["DATE"]
            try:
                # temperature values are given in tenths of degrees Celsius. In this case, we need to divide the values by 10 
                min_temp = (float(int(row["TMIN"].strip())) / 10) * (9 / 5) + 32  # Convert from Celsius to Fahrenheit
                max_temp = (float(int(row["TMAX"].strip())) / 10) * (9 / 5) + 32  # Convert from Celsius to Fahrenheit
                temperature_data[date_str] = (min_temp, max_temp)
            except ValueError:
                print(f"Skipping row with non-numeric temperature data: {row}")
    else:
        print("Could not get temperature data!!")

    csv_string = io.StringIO()
    fieldnames = ["DATE", "TMIN", "TMAX"]
    writer = csv.DictWriter(csv_string, fieldnames=fieldnames)

    writer.writeheader()
    for date_str, (min_temp, max_temp) in temperature_data.items():
        writer.writerow({"DATE": date_str, "TMIN": min_temp, "TMAX": max_temp})
    return csv_string.getvalue()

def main(latitude, longitude, startStr, endStr):
    nearest_station_id = find_closest_ghcnd_station(latitude, longitude, fileds, startStr, endStr)

    if nearest_station_id:
        print(f"Nearest station ID with good data: {nearest_station_id[0]}")
        temperature_data = fetch_temperature_data(nearest_station_id[0], startStr, endStr)
        # save csv file locally
        script_directory = os.path.dirname(os.path.abspath(__file__))
        csv_file_path = os.path.join(script_directory, f"{nearest_station_id[0]}_temperature_data.csv")
        with open(csv_file_path, "w") as csv_file:
            csv_file.write(temperature_data)
        return nearest_station_id[0], temperature_data
    else:
        print("No station found near the specified location.")
        return None


if __name__ == "__main__":
    # use this as example
    # Get the current date and time
    current_datetime = datetime.now()
    # Calculate one week ago
    endStr = current_datetime - timedelta(weeks=2)
    # Calculate 5 years and 1 week ago
    startStr = current_datetime - timedelta(weeks=2, days=365*5)
    
    latitude = 39.045002
    longitude = -106.257903

    id, temp_data = main(latitude, longitude, startStr, endStr)
