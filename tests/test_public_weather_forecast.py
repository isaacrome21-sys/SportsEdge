from copy import deepcopy
from datetime import datetime, timezone
import unittest
from urllib.parse import parse_qs, urlparse
from sportsedge.public_weather_forecast import forecast_url, kickoff_hour_forecast

START = datetime(2026,9,19,0,25,tzinfo=timezone.utc)

def payload():
    return {'utc_offset_seconds':0,
            'hourly_units':{'time':'unixtime','temperature_2m':'°F','wind_speed_10m':'mp/h','precipitation_probability':'%'},
            'hourly':{'time':[int(START.replace(minute=0).timestamp())],
                      'temperature_2m':[72.0],'wind_speed_10m':[9.0],'precipitation_probability':[25]}}

class PublicForecastTests(unittest.TestCase):
    def test_explicit_units_coordinates_and_utc_query(self):
        query=parse_qs(urlparse(forecast_url(40,-88,START)).query)
        self.assertEqual(query['timezone'],['UTC'])
        self.assertEqual(query['temperature_unit'],['fahrenheit'])
        self.assertEqual(query['wind_speed_unit'],['mph'])
        self.assertEqual(query['timeformat'],['unixtime'])

    def test_kickoff_hour_is_forecast_not_historical_vintage(self):
        result=kickoff_hour_forecast(payload(),START)
        self.assertEqual(result['temperature_f'],72)
        self.assertEqual(result['wind_mph'],9)
        self.assertFalse(result['historical_availability_proven'])
        self.assertEqual(result['forecast_valid_at_utc'],'2026-09-19T00:00:00+00:00')

    def test_bad_units_missing_hour_null_or_nonfinite_fail_closed(self):
        for case in ('units','hour','null','nan','duplicate'):
            data=deepcopy(payload())
            if case=='units':data['hourly_units']['wind_speed_10m']='km/h'
            if case=='hour':data['hourly']['time']=[0]
            if case=='null':data['hourly']['temperature_2m']=[None]
            if case=='nan':data['hourly']['temperature_2m']=[float('nan')]
            if case=='duplicate':data['hourly']['time']*=2
            with self.subTest(case=case), self.assertRaises(ValueError):
                kickoff_hour_forecast(data,START)

    def test_missing_or_invalid_venue_coordinates_not_guessed(self):
        for lat,lon in ((None,-88),(float('nan'),-88),(91,-88),(True,-88)):
            with self.subTest(lat=lat),self.assertRaises(ValueError):
                forecast_url(lat,lon,START)

if __name__=='__main__':unittest.main()
