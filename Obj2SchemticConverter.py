import os
import pandas as pd
import numpy as np
import json
from tqdm import tqdm

import pywavefront
from nbtlib import nbt, tag


class Obj2SchematicConverter(object):
    def __init__(self, obj_path, output_dir, height_max, width_max):
        '''
        constructor
        '''
        # DataFrame Column
        self.coordinates = ['x', 'y', 'z']
        self.colors = ['r', 'g', 'b']
        self.denorm_colors = ['denorm_r', 'denorm_g', 'denorm_b']
        self.coor_id = 'coordinate_id'

        if output_dir == None:
            self.output_dir = os.path.join(
                os.path.dirname(__file__), 'output')
        else:
            self.output_dir = output_dir
        self.HEIGHT_MAX = height_max
        self.WIDTH_MAX = width_max
        self.typical_colors = {}
        self.blocks = []
        self.data = []
        self.out_schem = os.path.splitext(os.path.basename(obj_path))[
            0] + '.schematic'

        # create .obj DataFrame
        scene = pywavefront.Wavefront(obj_path, parse=False)
        self.df = pd.DataFrame(
            scene.vertices, columns=self.coordinates + self.colors)

        self._preprocess_data()
        self._load_config()

    def _preprocess_data(self):
        '''
        preprocess .obj data
        '''
        print('start data preprocessing...')
        # coordinates
        self._move_to_zero_point()
        self._zoom_coordinates()
        self._round_down_coordinates()
        # color
        self._denormalize_color()

        self._add_coordinate_id_col()

    def _move_to_zero_point(self):
        '''
        x,y,z座標を0始点に変換
        '''
        self.df[self.coordinates] = self.df[self.coordinates] - \
            self.df[self.coordinates].apply(min)

    def _zoom_coordinates(self):
        '''
        指定された最大値になるように座標値を拡大する
        '''
        max_series = self.df[self.coordinates].apply(max)
        max_val = max_series.max()
        max_idx = max_series.idxmax()
        if max_idx in ['x', 'z']:
            zoom_ratio = self.WIDTH_MAX / max_val
        else:
            zoom_ratio = self.HEIGHT_MAX / max_val
        self.df[self.coordinates] = self.df[self.coordinates] * zoom_ratio

    def _round_down_coordinates(self):
        self.df[self.coordinates] = self.df[self.coordinates].apply(
            np.floor).astype(int)

    def _denormalize_color(self):
        '''
        正規化された色情報を復元する
        '''
        COLOR_MAX = 255
        self.df[self.denorm_colors] = self.df[self.colors] * COLOR_MAX

    def _add_coordinate_id_col(self):
        '''
        ボクセル位置を表す識別子用の列を追加
        '''
        self.df[self.coor_id] = self.df[self.coordinates].apply(
            self._gen_coordinates_id, axis=1)

    def _gen_coordinates_id(self, row):
        '''
        DataFrameの各行をコンマ区切りも文字列に変換する
        '''
        return ','.join([str(v) for v in row.values])

    def _load_config(self):
        with open(os.path.join(os.path.dirname(__file__), 'config/block_info.json'), 'r', encoding='utf-8') as f:
            self.config = json.load(f)

    def _calc_nearest_block(self, obj_color, config):
        best = float('inf')
        for c in config:
            p_color = c['COLOR']
            diff = obj_color - p_color
            diff_dist = sum(diff ** 2)
            if best > diff_dist:
                best = diff_dist
                color_data = c
                if best == 0:
                    break
        return color_data

    def convert(self):
        print('start converting...')
        voxels = self._calc_voxel_color()
        self._convert_to_block(voxels)

    def _calc_voxel_color(self):
        '''
        各ボクセルの色の代表値を決める
        '''
        for coor_id_val in tqdm(set(self.df[self.coor_id])):
            target = self.df[self.df[self.coor_id] ==
                             coor_id_val][self.colors + self.denorm_colors]
            self.typical_colors[coor_id_val] = target.mean()

        #
        bounds_e = self.df[self.coordinates].apply(max)
        voxels = np.zeros(
            list((bounds_e + 1).apply(np.ceil).values.astype(int)) + [3])
        for coor, color in tqdm(self.typical_colors.items()):
            x, y, z = [int(v) for v in coor.split(',')]
            voxels[x, y, z] = color[self.denorm_colors].values
        return voxels

    def _convert_to_block(self, voxels):
        self.width, self.height, self.length = voxels.shape[:3]
        for y in tqdm(range(self.height)):
            for z in range(self.length):
                for x in range(self.width):
                    if (voxels[x, y, z] == 0).all():
                        # air
                        self.blocks.append(0)
                        self.data.append(0)
                    else:
                        color_data = self._calc_nearest_block(
                            voxels[x, y, z], self.config)
                        self.blocks.append(color_data['BLOCK_ID'])
                        self.data.append(color_data['DATA'])

    def output(self):
        schem = nbt.load(os.path.join(
            os.path.dirname(__file__), 'empty_schematic'))
        out_path = os.path.join(self.output_dir, self.out_schem)
        os.makedirs(self.output_dir, exist_ok=True)
        self._packing(schem)
        self._save_schematic(out_path, schem)

    def _packing(self, schematic_obj):
        schematic_obj.root['Blocks'] = tag.ByteArray(self.blocks)
        schematic_obj.root['Data'] = tag.ByteArray(self.data)
        schematic_obj.root['Width'] = tag.Short(self.width)
        schematic_obj.root['Length'] = tag.Short(self.length)
        schematic_obj.root['Height'] = tag.Short(self.height)

    def _save_schematic(self, out_file, schematic_obj):
        schematic_obj.save(out_file)
        print('successfully finished: ', out_file)


def get_args():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("obj_file",
                        help="input .obj file path")
    parser.add_argument('--output_dir', type=str, default=None,
                        help='Output dir of generated .schematic file.')
    parser.add_argument('--h_max', type=int, default=100,
                        help='Max height of converted schematic object.')
    parser.add_argument('--w_max', type=int, default=100,
                        help='Max width(length) of converted schematic object.')
    args = parser.parse_args()
    return args


if __name__ == '__main__':
    try:
        print('checking arguments...')
        args = get_args()
        print('start converting...')
        converter = Obj2SchematicConverter(
            args.obj_file, args.output_dir, args.h_max, args.w_max)
        converter.convert()
        converter.output()
    except Exception as e:
        print('convert failed: ', e)
