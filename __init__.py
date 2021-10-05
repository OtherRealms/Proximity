# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name" : "Proximity",
    "author" : "Pablo Tochez A.",
    "description" : "For generating proximity and tension weights",
    "blender" : (2, 90, 0),
    "version" : (0, 1, 6),
    "location" : "3D view right panel",
    "warning" : "",
    "category" : "Mesh"
}


import collections
import bpy,bmesh
from functools import lru_cache
from bpy.props import*
from mathutils import Vector,kdtree
from bpy.app.handlers import persistent
from bpy.types import AddonPreferences,Operator,Panel
from .bake import PROXIMITY_OT_install_PILLOW,PROXIMITY_PT_BakePanel,PROXIMITY_OT_bake,is_ready

@lru_cache(maxsize=32)
def included_verts(ids,obj,filter_verts,filter_id):
    inc_verts = []

    for id in ids:
        included = True
        if filter_verts:
            included = False
            original_vert = obj.data.vertices[id]
            for g in original_vert.groups:
                if g.group == filter_id and g.weight > 0.01:
                    included = True
                    break
        
        if not included:
            continue

        
        inc_verts.append(id)

    return tuple(inc_verts)

@lru_cache(maxsize=32)
def included_edges(obj,inc_verts):
    inc_edges = []

    for edge in obj.data.edges:
        id_a = edge.vertices[0]
        id_b = edge.vertices[1]

        if id_a not in inc_verts:
                continue
        
        #original Verts 
        vert_a = obj.data.vertices[id_a]
        coA =  vert_a.co

        vert_b = obj.data.vertices[id_b]
        coB =  vert_b.co

        original_dist = distance_vec(coA,coB)
        inc_edges.append((id_a,id_b,original_dist))

    return tuple(inc_edges)


@lru_cache(maxsize=32)
def get_vert_ids(obj):
    size = len(obj.data.vertices)
    ids = [0]*size
    obj.data.vertices.foreach_get('index',ids)
    return tuple(ids)   


@persistent
def execute(scene,deps_graph):
    #scene = bpy.context.scene
    #deps_graph= bpy.context.evaluated_depsgraph_get() 

    for grp in scene.proximity_objects:
        if grp.live and grp.object and grp.object.mode != 'EDIT':
            obj = grp.object
            collection = grp.collection
            if grp.mode == 'Proximity_obj' and not collection:
                return

            for mod in obj.modifiers:
                if mod.type == 'CLOTH':
                    if not mod.point_cache.is_baked:
                        return
                         

            ranged_grp = grp.vertex_group_ranged 
            threshold_grp = grp.vertex_group_threshold
            ranged_id = None
            threshold_id = None

            #assign and set defaults
            obj_eval = None
            

            #refresh cache
            if scene.frame_current == scene.frame_start:
                get_vert_ids.cache_clear()
                included_edges.cache_clear()
                included_verts.cache_clear()

            if grp.mode in ('Proximity','Tension'):
                obj_eval= obj.evaluated_get(deps_graph)
                ids = get_vert_ids(obj)
                

                reset = not grp.cumulative or scene.frame_current == scene.frame_start
                #Reset weights
                if ranged_grp and ranged_grp in obj.vertex_groups.keys(): 
                    ranged_id = obj.vertex_groups[ranged_grp].index
                    if reset:
                        if grp.mode == 'Proximity':
                            obj.vertex_groups[ranged_grp].add(ids, 0, 'REPLACE' )
                        if grp.mode == 'Tension':
                            obj.vertex_groups[ranged_grp].add(ids, 0.5, 'REPLACE' )

                if threshold_grp and threshold_grp in obj.vertex_groups.keys(): 
                    threshold_id = obj.vertex_groups[threshold_grp].index
                    if reset:
                        obj.vertex_groups[threshold_grp].add(ids, 0, 'REPLACE')
            else:
                #Proximity objects
                collection_filtered= []

                for object in collection.objects:
                    if not object or object.type != 'MESH':
                        continue
                    collection_filtered.append(object)
                    

                    ids = get_vert_ids(object)
                    #Reset weights

                    if not grp.cumulative or scene.frame_current == scene.frame_start:
                        if ranged_grp and ranged_grp in object.vertex_groups.keys():
                            object.vertex_groups[ranged_grp].add(ids, 0, 'REPLACE' )

                        if threshold_grp and threshold_grp in object.vertex_groups.keys(): 
                            object.vertex_groups[threshold_grp].add(ids, 0, 'REPLACE' )

            #-------------Mode---------
            
            
            if ranged_grp or threshold_grp:
                is_ready[0] = False
                
                if grp.mode == 'Proximity':
                    vert_proximity(grp,
                                obj=obj,
                                obj_eval=obj_eval,
                                ranged_id= ranged_id,
                                threshold_id= threshold_id, 

                                )
                elif grp.mode == 'Proximity_obj':
                    target = obj.evaluated_get(deps_graph)
                    object_proximity(grp,
                                target = target,
                                collection_filtered = collection_filtered,
                                ranged_grp = ranged_grp,
                                threshold_grp = threshold_grp,
                                depsgraph= deps_graph

                                )

                elif grp.mode == 'Tension':
                    vert_tension(grp,
                                obj=obj,
                                obj_eval=obj_eval,
                                ranged_id= ranged_id,
                                threshold_id= threshold_id, 
                                )

                is_ready[0] =True

def vert_proximity(grp,obj,obj_eval,ranged_id,threshold_id):
    range_m = grp.range_multiplier
    proximity = grp.proximity
    filter_verts = grp.vertex_group_filter
    cooldown = grp.cooldown

    filter_id = None

    ids = get_vert_ids(obj)

    if filter_verts:
        filter_id = obj.vertex_groups[filter_verts].index

    length = len(ids)

    positions = []
    kd = kdtree.KDTree(length) 

    inc_verts = included_verts(ids,obj,filter_verts,filter_id)

    for id in inc_verts:
        vert = obj_eval.data.vertices[id]
        co = obj.matrix_world @ vert.co
        positions.append((co,vert.index))
        kd.insert(co, vert.index)

    kd.balance()

    #Each point
    for co,id in positions:
        #each point compared to this point
        n = kd.find_n(co,2)
        
        for point in n:
            _co,_id,dist = point
            dist = round(dist,4)

            if _id == id:
                continue

            vert_a = obj.data.vertices[id]

            if grp.invert:
                ranged_val = max(min((dist - proximity) /(proximity*range_m -proximity),1),0)
            else:
                ranged_val = max(min((dist - proximity*range_m)/(proximity - proximity*range_m),1),0)

            
            threshold_val = 1 if dist  < proximity else 0

            if grp.cumulative:
                set_weights_cumulative(vert_a,ranged_id,threshold_id,ranged_val,threshold_val,cooldown)
            else:
                set_weights(vert_a,ranged_id,threshold_id,ranged_val,threshold_val)
    
def object_proximity(grp,target,collection_filtered,ranged_grp,threshold_grp,depsgraph):
    range_m = grp.range_multiplier
    proximity = grp.proximity
    filter_grp = grp.vertex_group_filter
    count = len(collection_filtered)
    neighbours = grp.neighbours if not grp.cumulative else count    
    threshold_id = None
    cooldown = grp.cooldown


    #make object KD tree
    kd = kdtree.KDTree(count) 

    for index, object in enumerate(collection_filtered,start = 0):
        obj_e = object.evaluated_get(depsgraph)
        co =  obj_e.matrix_world.translation
        
        kd.insert(co,index)

    kd.balance()

    #Find nearest objects
    target_co = target.matrix_world.translation
    nearest = kd.find_n(target_co,neighbours)
    

    for item in nearest:
        _co,_idx,dist = item

        if proximity <= proximity:
            ranged_id = None
            threshold_id = None
            object = collection_filtered[_idx]
            if filter_grp in object.vertex_groups.keys():
                filter_id = object.vertex_groups[filter_grp].index

            if ranged_grp in object.vertex_groups.keys():
                ranged_id = object.vertex_groups[ranged_grp].index
                

            if threshold_grp in object.vertex_groups.keys():
                threshold_id = object.vertex_groups[threshold_grp].index


            ranged_val = max(0,(dist - proximity*range_m)/(proximity-proximity*range_m))
            threshold_val = 1 if dist  < proximity else 0

            for vert in object.data.vertices:
                included = False
                

                if filter_grp:
                    included = False
                    for g in vert.groups:
                        if g.group == filter_id and g.weight > 0.01:
                            included = True
                            break
                else:
                    included = True

                if included:
                    if grp.cumulative:
                        set_weights_cumulative(vert,ranged_id,threshold_id,ranged_val,threshold_val,cooldown)
                    else:
                        set_weights(vert,ranged_id,threshold_id,ranged_val,threshold_val)

def set_weights(vert,ranged_id,threshold_id,ranged_val,threshold_val):
    
    for group in vert.groups:
        if ranged_id != None and group.group == ranged_id:
            group.weight = ranged_val

        elif threshold_id != None and group.group == threshold_id:
            group.weight = threshold_val

def set_weights_cumulative(vert,ranged_id,threshold_id,ranged_val,threshold_val,cooldown):
    for group in vert.groups:
        if group.group == ranged_id:
            gw = group.weight
            if ranged_val > gw :
                group.weight  = min(1,gw  + ranged_val*0.5)
            elif cooldown > 0:
                group.weight  = max(0,gw  - cooldown)

        elif group.group == threshold_id:
            gw = group.weight
            if threshold_val > gw:
                group.weight += min(1,threshold_val)
            elif cooldown > 0:
                group.weight= max(0,gw - cooldown )

def vert_tension(grp,obj,obj_eval,ranged_id,threshold_id):
    filter_verts = grp.vertex_group_filter
    bias = grp.bias * 0.1
    ids = get_vert_ids(obj)

    cooldown = grp.cooldown

    filter_id = None
    if filter_verts:
        filter_id = obj.vertex_groups[filter_verts].index

    inc_verts = included_verts(ids,obj,filter_verts,filter_id)

    inc_edges = included_edges(obj,inc_verts)

    tension_distance = grp.tension_distance
    
    
    weights = collections.defaultdict(float)

    distances = collections.defaultdict(list)

    for id_a,id_b,original_dist in inc_edges:

        #deformed Verts 
        eval_vert_a = obj_eval.data.vertices[id_a]
        eval_co_a = eval_vert_a.co

        eval_vert_b = obj_eval.data.vertices[id_b]
        eval_co_b = eval_vert_b.co

        #distances
        new_dist = distance_vec(eval_co_a,eval_co_b)

        dist = round(new_dist -original_dist,4)
        neighbour_a = (id_a,dist)
        neighbour_b = (id_b,dist)

        distances[id_a].append(neighbour_b)
        distances[id_b].append(neighbour_a)


    for id in distances:
        neighbours = distances.get(id)
        dists= [x[1] for x in neighbours]
        #print(d)

        #smallest and largest
        s,l = min(dists),max(dists)

        distance_inv = tension_distance * -1 
        if grp.dominance == 'Dominant':
            #take the most extreme
            if  abs(s)-bias > abs(l):#s-bias 
                dist = s
            else:
                dist = l
        else:
            #average
            dist = (s + l+bias)/2
      
        if grp.invert:
            ranged_val = max(min((dist - tension_distance) /(distance_inv - tension_distance),1),0)
        else:
            ranged_val = max(min((dist - distance_inv) /(tension_distance - distance_inv),1),0)
    

        weights[id]=ranged_val


        if threshold_id:
            if s < distance_inv or l > tension_distance:
                threshold_val = 1
            else:
                threshold_val = 0
        else:
            threshold_val = 0

        if not grp.average or threshold_id:
            vert= obj.data.vertices[id]

            #block ranged val from being set if smooth weights
            if grp.average:
                temp_ranged_id = None
            else:
                temp_ranged_id = ranged_id

            if grp.cumulative:
                set_weights_cumulative(vert,temp_ranged_id,threshold_id,ranged_val,threshold_val,cooldown)
            else:
                set_weights(vert,temp_ranged_id,threshold_id,ranged_val,threshold_val)
                

    if grp.average:
        iterations = grp.iterations
        for n in range(iterations):
            last = True if n == iterations-1 else False
            #print(n,last)
            average(obj,weights,distances,ranged_id,last,grp)

    del distances
    del weights

def average(obj,weights,distances,ranged_id,last,grp):
    
    for id in distances:
        n = distances.get(id)
        n_ids = [x[0] for x in n]

        neighbour_weights = []
        current_weight = weights[id]

        
        for v_id in n_ids:
            v_weight = weights[v_id]
            
            neighbour_weights.append(v_weight)
        
        if neighbour_weights:
            s,l = min(neighbour_weights),max(neighbour_weights)

            if l-s > 0:
                ranged_val = (s+l+current_weight)/3 
                weights[id] = ranged_val

                if last:
                    vert_a = obj.data.vertices[id]
                    if grp.cumulative:
                        set_weights_cumulative(vert_a,ranged_id,None,ranged_val,0,grp.cooldown)
                    else:
                        set_weights(vert_a,ranged_id,None,ranged_val,0)  

            else:
                #print(s,l)
                ranged_val = current_weight
                if last:
                    vert_a = obj.data.vertices[id]
                    if grp.cumulative:
                        set_weights_cumulative(vert_a,ranged_id,None,ranged_val,0,grp.cooldown)
                    else:
                        set_weights(vert_a,ranged_id,None,ranged_val,0)   

def distance_vec(point1: Vector, point2: Vector) -> float:
    return (point2 - point1).length

def update_prop(self,context):
    deps_graph= context.evaluated_depsgraph_get() 
    execute(context.scene,deps_graph)

class PROXIMITY_PT_panel(Panel):
    bl_label = "Proximity"
    bl_idname = "PROXIMITY_PT_panel"
    bl_space_type =  'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Proximity"


    def draw(self,context):
        layout = self.layout
        scene = context.scene
        row = layout.row()
        row = row.split()
        row.operator("proximity.add_object",icon = 'ADD')
        row.separator()
        layout.box()


        for index,grp in enumerate(scene.proximity_objects):
            row = layout.row()
            
            name = ' '
            if grp.object:
                name += grp.object.name
                if grp.live:
                    is_baked = True
                    for mod in grp.object.modifiers:
                        if mod.type == 'CLOTH' and not mod.point_cache.is_baked:
                            row.alert = True
                            name += ' :CLOTH NOT BAKED'
                            row.label(text = '',icon = 'PROP_OFF')
                            is_baked= False
                    if is_baked:
                        name += ' :LIVE'
                        row.prop(grp,'live',text = '',icon = 'PROP_ON',emboss = False)
                else:
                    row.prop(grp,'live',text = '',icon = 'PROP_OFF',emboss = False)

            arrow = 'DISCLOSURE_TRI_DOWN' if grp.expand else 'DISCLOSURE_TRI_RIGHT'
            row.prop(grp,'expand',text= name,icon = arrow,emboss = False)
            
            row.operator("proximity.delete_object",text = '',icon = 'TRASH').index = index

            if grp.expand:
                layout.prop(grp,'mode')
                
                layout.prop(grp,'object')

                obj = grp.object

                if grp.mode =='Tension':
                    layout.prop(grp,'tension_distance')
                    col = layout.column()
                    if not grp.vertex_group_ranged and not grp.vertex_group_threshold:
                        col.enabled = False
                    col.prop(grp,'bias')
                    col.prop(grp,'invert')
                    row = col.row()
                    row.prop(grp,'average')
                    row.prop(grp,'iterations')
                    row = col.row()
                    row.prop(grp,'dominance')
                    col.prop(grp,'cumulative')
                    if grp.cumulative:
                        col.prop(grp,'cooldown')


                elif grp.mode =='Proximity':
                    layout.prop(grp,'proximity')
                    layout.prop(grp,'range_multiplier')
                    layout.prop(grp,'invert')
                    layout.prop(grp,'cumulative')
                    if grp.cumulative:
                        layout.prop(grp,'cooldown')

                elif grp.mode == 'Proximity_obj':
                    layout.prop(grp,'proximity')
                    layout.prop(grp,'range_multiplier')
                    layout.prop(grp,'collection')
                    layout.prop(grp,'cumulative')
                    if grp.cumulative:
                        layout.prop(grp,'cooldown')
                    else:
                        layout.prop(grp,'neighbours')
                    if grp.collection and grp.collection.objects:
                        obj = grp.collection.objects[0]
                    
                    
                if obj:
                    row = layout.row()
                    row.prop_search(grp, "vertex_group_threshold", obj, "vertex_groups", text="Threshold")   

                    add = row.operator("proximity.make_vertgroup",text = '',icon = 'ADD')
                    add.index = index
                    add.type = 'Threshold'

                    row = layout.row()
                    row.prop_search(grp, "vertex_group_ranged", obj, "vertex_groups", text="Ranged")
                    add = row.operator("proximity.make_vertgroup",text = '',icon = 'ADD') 
                    add.index = index
                    add.type = 'Ranged'

                    row = layout.row()
                    row.prop_search(grp, "vertex_group_filter", obj, "vertex_groups", text="Filter")
                    add = row.operator("proximity.make_vertgroup",text = '',icon = 'ADD') 
                    add.index = index
                    add.type = 'Filter'

                    
                    layout.operator("proximity.bake",icon ='DOCUMENTS').grp = index

                layout.box()

class PROXIMITY_OT_add_object(Operator):
    bl_idname = "proximity.add_object" 
    bl_label = "Add Object" 
    bl_options = {'UNDO'}

    def execute(self, context): 
        scene = context.scene
        scene.proximity_objects.add()
        return {'FINISHED'}   

class PROXIMITY_OT_delete_object(Operator):
    bl_idname = "proximity.delete_object" 
    bl_label = "Delete Object" 
    bl_options = {'UNDO'}

    index : IntProperty()

    def execute(self, context): 
        scene = context.scene
        scene.proximity_objects.remove(self.index)
        return {'FINISHED'}   

class PROXIMITY_OT_make_vertGroup(Operator):
    bl_idname = "proximity.make_vertgroup" 
    bl_label = "Create vertex group" 
    bl_options = {'UNDO'}

    index : IntProperty()
    type : StringProperty()

    def execute(self, context): 
        scene = context.scene
        grp = scene.proximity_objects[self.index]
        if grp.mode in ('Proximity','Tension'):
            if grp.object and self.type not in grp.object.vertex_groups.keys():
                grp.object.vertex_groups.new(name=self.type)
                if self.type == 'Threshold':
                    grp.vertex_group_threshold = self.type
                elif self.type == 'Ranged':
                    grp.vertex_group_ranged = self.type
                elif self.type == 'Filter':
                    grp.vertex_group_filter = self.type
            else:
                self.report({'ERROR'},"No object has been assigned or group already exists")
        else:
            if grp.collection:
                for object in grp.collection.objects:
                    if self.type not in object.vertex_groups.keys():
                        object.vertex_groups.new(name=self.type)

                if self.type == 'Threshold':
                    grp.vertex_group_threshold = self.type
                elif self.type == 'Ranged':
                    grp.vertex_group_ranged = self.type
                elif self.type == 'Filter':
                    grp.vertex_group_filter = self.type

            else:
                self.report({'ERROR'},"No collection has been assigned")
        return {'FINISHED'}   
  
class Proximity_objects(bpy.types.PropertyGroup):
    object : PointerProperty(name = 'Object',type = bpy.types.Object)

    collection : PointerProperty(name = 'Collection',type = bpy.types.Collection)

    neighbours : IntProperty(name = 'Neighbours',min = 0,default = 6,update =update_prop)

    proximity : FloatProperty(
        min = 0.000001,
        default = 0.1,
        name = 'Distance',
        subtype = 'DISTANCE',
        update =update_prop,
        description="Proximity distance threshold for points in from a single source"
        )
    bias : FloatProperty(
        default = 0,
        min = -50,
        max = 50,
        update = update_prop,
        description="Ranged compression/stretch bias"
        )

    iterations : IntProperty(
        name = 'Iterations',
        min = 1,
        max = 16,
        default = 1,
        update = update_prop)

    tension_distance : FloatProperty(
        min = 0.000001,
        default = 0.2,
        name = 'Threshold',
        subtype = 'DISTANCE',
        description="Minimum vertex displacement before detecting streching or compression",
        update = update_prop
        )

    dominance : EnumProperty(
        name = 'Dominance',
        items=(('Average','Average','Average'),
        ('Dominant','Dominant','Dominant')),
        description="Favour either an average or dominant of stretch/compression when both values are high.",
        update =update_prop
        )

    vertex_group_ranged: StringProperty(
        update =update_prop,
        description="Vertex group for threshold with added falloff"
        )

    vertex_group_threshold: StringProperty(
        update =update_prop,
        description="Vertex group for binary threshold"
        )
    
    vertex_group_filter: StringProperty(
        update =update_prop,
        description="Vertex group to determine included vertices for calculation"
        )


    range_multiplier: FloatProperty(
        name = 'Range 1x',min = 1.1,
        default = 1.1,
        update =update_prop,
        description="Extend the ranged falloff"
        )

    mode : EnumProperty(
        items=(
            ('Proximity','Vertices Proximity','Proximity for verts within a single mesh',0),
            ('Proximity_obj','Objects Proximity','Proximity from target object to collection objects',1),
            ('Tension','Tension','Compression and stretch of polys within a single mesh',2)),
        update =update_prop
        )


    live: BoolProperty(
        name='Live',
        default = True,
        description="Enable updates on frame change",
        update =update_prop
        )
    average: BoolProperty(
        name='Smooth',
        default = False,
        description="Smooth ranged mapping with performance cost",
        update =update_prop
        )
    cumulative : BoolProperty(name='Cumulative')
    
    cooldown : FloatProperty(min = 0, max = 1,name = 'Cool Down',description = "The amount of weight reduced per frame, higher is faster. TIP: try very low values like 0.001")
    
    invert : BoolProperty(
        name = "Invert Weights",
        default= False,
        update =update_prop)

    expand : BoolProperty(default= True)


classes = [
    PROXIMITY_PT_panel,
    PROXIMITY_OT_add_object,
    PROXIMITY_OT_delete_object,
    PROXIMITY_OT_make_vertGroup,
    Proximity_objects,
    PROXIMITY_OT_install_PILLOW,
    PROXIMITY_PT_BakePanel,
    PROXIMITY_OT_bake

    ]

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.app.handlers.frame_change_post.append(execute)
    bpy.types.Scene.proximity_objects = CollectionProperty(type = Proximity_objects)
    bpy.types.Scene.proximity_output = StringProperty(name = 'Directory',subtype = 'DIR_PATH')



def unregister():
    from bpy.utils import unregister_class
    for cls in classes:
        unregister_class(cls)
    
    bpy.app.handlers.frame_change_post.remove(execute)
    del bpy.types.Scene.proximity_objects
    del bpy.types.Scene.proximity_output 

