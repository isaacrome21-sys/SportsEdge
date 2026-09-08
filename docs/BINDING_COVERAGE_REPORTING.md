# Coverage reporting

Coverage must distinguish `PASS`, `BLOCKED`, and `UNAUDITABLE/IDENTITY_MISSING`. A missing adapter identity is not a model failure and is not PASS. The report should count every priced row presented to normalization, including rows blocked before engine execution, so early failures cannot disappear from coverage.
