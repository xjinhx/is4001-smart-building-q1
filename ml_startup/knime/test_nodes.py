"""Run the KNIME node code against a stand-in for knime.scripting.io (KNIME itself is not used).
Skips node 1 and 3's slow retraining unless you pass --all."""
import sys
import types
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nodes


class Table:
    def __init__(self, df):
        self.df = df

    @staticmethod
    def from_pandas(df):
        assert isinstance(df, pd.DataFrame) and len(df)
        return Table(df)

    def to_pandas(self):
        return self.df


class Slots(dict):
    def __setitem__(self, k, v):
        super().__setitem__(k, v)


io = types.ModuleType('knime.scripting.io')
io.Table = Table
io.flow_variables = {'ml_startup_dir': str(HERE.parent)}
sys.modules.update({'knime': types.ModuleType('knime'), 'knime.scripting': types.ModuleType('knime.scripting'),
                    'knime.scripting.io': io})

run = ['NODE_2_VALIDATE', 'NODE_4_SCHEDULE_OUT', 'NODE_5_DAY_TYPE_SCHEDULES']
if '--all' in sys.argv:
    run = ['NODE_1_PREPARE', 'NODE_2_VALIDATE', 'NODE_3_OPTIMISE', 'NODE_4_SCHEDULE_OUT', 'NODE_5_DAY_TYPE_SCHEDULES']
day = pd.read_csv(HERE.parent.parent / 'IS4001_Q1_Haritha' / 'IS4001_Q1_Haritha' / 'data' / 'day_table.csv')
day = day[day.working]
# Stand-in day types, just to exercise Dessy's node
day_types = pd.DataFrame({'date': day.date, 'day_type': (day.kWh > day.kWh.median()).map({True: 'high', False: 'low'})})
for name in run:
    io.output_tables, io.output_images, io.input_tables = Slots(), Slots(), [Table(day_types)]
    exec(getattr(nodes, name), {})
    print(name, 'OK', {k: v.df.shape for k, v in io.output_tables.items()}, 'images', list(io.output_images))
    if name == 'NODE_5_DAY_TYPE_SCHEDULES':
        print(io.output_tables[0].df.pivot(index=['floor', 'zone'], columns='day_type', values='offset_min').T.to_string())
