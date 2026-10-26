import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from database.reader.v2 import prepare_refresh


FIPS = ["01","02","04","05","06","08","09","10","11","12","13","15","16","17","18","19","20","21","22","23","24","25","26","27","28","29","30","31","32","33","34","35","36","37","38","39","40","41","42","44","45","46","47","48","49","50","51","53","54","55","56"]
HEADERS = ["field_id","geo_type","geo_id","state_abbr","state_name","source_state_name","source_footnote_marker","period","period_type","value","unit","numerator_count","denominator_population","source_field","source_adjustment","source_release","source_url","retrieved_at","source_sha256","caveats"]


def fixture_rows():
    rows=[]
    for field,(source_field,_label) in prepare_refresh.FBI_FIELDS.items():
        for geo_type,geo_id,state_abbr,state_name,pop,source_state_name,marker,caveat in [
            ("nation","US","US","United States Total",341784857,"United States Total","",""),
            *[("state",fips,"CA" if fips=="06" else fips,"California" if fips=="06" else "Florida" if fips=="12" else "North Dakota" if fips=="38" else "District of Columbia" if fips=="11" else "State",39355309 if fips=="06" else 1000000,"     Florida3" if fips=="12" else "     North Dakota3" if fips=="38" else "     District of Columbia4" if fips=="11" else "State","3" if fips in ("12","38") else "4" if fips=="11" else "","limited data for Florida and North Dakota." if fips in ("12","38") else "DC special agency coverage" if fips=="11" else "") for fips in FIPS]
        ]:
            numerator=1370 if geo_id=="06" and source_field=="homicide" else 13130 if geo_id=="06" and source_field=="rape_revised" else 10
            if geo_id=="06" and source_field=="homicide": pop=39355309
            row={"field_id":field,"geo_type":geo_type,"geo_id":geo_id,"state_abbr":state_abbr,
                 "state_name":state_name,"period":"2025","period_type":"annual",
                 "source_state_name":source_state_name,"source_footnote_marker":marker,
                 "value":str(Decimal(numerator)/Decimal(pop)*100000),"unit":"per 100,000",
                 "numerator_count":str(numerator),"denominator_population":str(pop),"source_field":source_field,
                 "source_adjustment":"official same-row population","source_release":prepare_refresh.FBI_RELEASE,
                 "source_url":prepare_refresh.FBI_SOURCE_URL,"retrieved_at":prepare_refresh.FBI_RETRIEVED_AT,
                 "source_sha256":prepare_refresh.FBI_RAW_SHA256,"caveats":caveat}
            rows.append(row)
    return rows


class PrepareFbiAnnualTests(unittest.TestCase):
    def invoke(self, rows):
        with tempfile.TemporaryDirectory() as temp:
            csv_path=Path(temp)/"prepared.csv"; raw_path=Path(temp)/"raw.bin"
            raw_path.write_bytes(b"fixture-only raw source marker")
            with csv_path.open("w",newline="",encoding="utf-8") as stream:
                writer=csv.DictWriter(stream,fieldnames=HEADERS); writer.writeheader(); writer.writerows(rows)
            def trusted_hash(path):
                return prepare_refresh.FBI_RAW_SHA256 if Path(path).resolve()==raw_path.resolve() else "a"*64
            with patch.object(prepare_refresh,"sha256",side_effect=trusted_hash), patch.object(prepare_refresh,"FBI_PREPARED_SHA256","a"*64):
                return prepare_refresh.prepare_fbi_annual(csv_path,"a"*64,raw_path,prepare_refresh.FBI_RAW_SHA256)

    def test_all_fields_native_us_ca_formula_and_caveats(self):
        rows=self.invoke(fixture_rows())
        self.assertEqual(len(rows),364)
        ca_homicide=next(r for r in rows if r["field_id"]=="04.01:derived" and r["geo_id"]=="06")
        self.assertEqual((ca_homicide["numerator_count"],ca_homicide["denominator_population"]),("1370","39355309"))
        us=next(r for r in rows if r["field_id"]=="04.07:derived" and r["geo_type"]=="nation")
        self.assertEqual((us["geo_id"],us["state_name"],us["denominator_population"]),("US","United States Total","341784857"))
        florida=next(r for r in rows if r["geo_id"]=="12")
        self.assertEqual(florida["state_name"],"Florida")
        self.assertTrue(florida["source_state_name"].strip().endswith("Florida3"))

    def test_incomplete_geography_is_rejected(self):
        rows=fixture_rows(); rows.pop()
        with self.assertRaisesRegex(ValueError,"exactly seven fields"):
            self.invoke(rows)

    def test_wrong_revised_rape_field_or_formula_is_rejected(self):
        rows=fixture_rows(); next(r for r in rows if r["field_id"]=="04.07:derived")["source_field"]="rape_legacy"
        with self.assertRaisesRegex(ValueError,"pinned source/field/year"):
            self.invoke(rows)
        rows=fixture_rows(); next(r for r in rows if r["field_id"]=="04.07:derived" and r["geo_id"]=="06")["value"]="0"
        with self.assertRaisesRegex(ValueError,"rate formula"):
            self.invoke(rows)

    def test_missing_district_caveat_or_non_native_us_is_rejected(self):
        rows=fixture_rows(); next(r for r in rows if r["geo_id"]=="11")["caveats"]=""
        with self.assertRaisesRegex(ValueError,"DC source footnote"):
            self.invoke(rows)
        rows=fixture_rows(); next(r for r in rows if r["field_id"]=="04.01:derived" and r["geo_type"]=="nation")["geo_id"]="01"
        with self.assertRaisesRegex(ValueError,"native United States"):
            self.invoke(rows)


if __name__=="__main__":
    unittest.main()
