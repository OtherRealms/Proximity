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
    "version" : (0, 1, 3),
    "location" : "3D view right panel",
    "warning" : "",
    "category" : "Mesh"
}


import bpy
import bmesh
from bpy.props import*
import mathutils
from mathutils import Vector,kdtree
from bpy.app.handlers import persistent
import collections
from bpy.props import *


@persistent
def execute(dummy):
    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get() 

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

            if grp.mode in ('Proximity','Tension'):
                obj_eval = bmesh.new()
                obj_eval.from_object(obj, dg, cage=True, face_normals=True)
                obj_eval.verts.ensure_lookup_table()
                obj_eval.faces.ensure_lookup_table()
                obj_eval.verts.layers.deform.verify()

                size = len(obj_eval.verts)
                ids = [0]*size

                obj.data.vertices.foreach_get('index',ids)

                if ranged_grp and ranged_grp in obj.vertex_groups.keys(): 
                    ranged_id = obj.vertex_groups[ranged_grp].index
                    if grp.mode == 'Proximity':
                        obj.vertex_groups[ranged_grp].add(ids, 0, 'REPLACE' )
                    if grp.mode == 'Tension':
                        obj.vertex_groups[ranged_grp].add(ids, 0.5, 'REPLACE' )

                if threshold_grp and threshold_grp in obj.vertex_groups.keys(): 
                    threshold_id = obj.vertex_groups[threshold_grp].index
                    obj.vertex_groups[threshold_grp].add(ids, 0, 'REPLACE')
            else:
                #Proximity objects

                for object in collection.objects:
                    if not object or object.type != 'MESH':
                        continue
                    size = len(object.data.vertices)
                    ids = [0]*size
                    object.data.vertices.foreach_get('index',ids)
                    if ranged_grp and ranged_grp in object.vertex_groups.keys():
                        object.vertex_groups[ranged_grp].add(ids, 0, 'REPLACE' )

                    if threshold_grp and threshold_grp in object.vertex_groups.keys(): 
                        threshold_id = object.vertex_groups[threshold_grp].index
                        object.vertex_groups[threshold_grp].add(ids, 0, 'REPLACE' )

            #-------------Mode---------
            
            if ranged_grp or threshold_grp:
                if grp.mode == 'Proximity':
                    vert_proximity(grp,
                                obj=obj,
                                obj_eval=obj_eval,
                                ranged_id= ranged_id,
                                threshold_id= threshold_id, 

                                )
                elif grp.mode == 'Proximity_obj':
                    target = obj.evaluated_get(dg)
                    object_proximity(grp,
                                target = target,
                                collection = collection,
                                ranged_grp = ranged_grp,
                                threshold_grp = threshold_grp ,
                                depsgraph= dg

                                )

                elif grp.mode == 'Tension':
                    vert_tension(grp,
                                obj=obj,
                                obj_eval=obj_eval,
                                ranged_id= ranged_id,
                                threshold_id= threshold_id, 
                                )

            if obj_eval:
                obj_eval.free()

def vert_proximity(grp,obj,obj_eval,ranged_id,threshold_id):
    range_m = grp.range_multiplier
    proximity = grp.proximity
    filter_verts = grp.vertex_group_filter

    if filter_verts:
        filter_id = obj.vertex_groups[filter_verts].index

    length = len(obj_eval.verts)

    positions = []
    kd = kdtree.KDTree(length) 

    for vert in obj_eval.verts:
        included = True

        if filter_verts:
            included = False
            o_vert = obj.data.vertices[vert.index]
            for g in o_vert.groups:
                if g.group == filter_id and g.weight >  0.01:
                    included = True
                    break
        
        if included:
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

            ranged_val = (dist - proximity*range_m)/(proximity-proximity*range_m)
            
            threshold_val = 1 if dist  < proximity else 0

            set_weights(vert_a,ranged_id,threshold_id,ranged_val,threshold_val)

def object_proximity(grp,target,collection,ranged_grp,threshold_grp,depsgraph):
    range_m = grp.range_multiplier
    proximity = grp.proximity
    filter_verts = grp.vertex_group_filter
    count = len(collection.objects)
    neighbours = grp.neighbours

    #make object KD tree
    kd = kdtree.KDTree(count) 



    for index, object in enumerate(collection.objects):
        obj= object.evaluated_get(depsgraph)
        co = obj.matrix_world @ obj.location
        kd.insert(co,index)

    kd.balance()

    #Find nearest objects
    target_co = target.matrix_world @ target.location
    n = kd.find_n(target_co,neighbours)

    for item in n:
        _co,_id,dist = item

        if proximity <= proximity:
            object = collection.objects[_id]

            size = len(object.data.vertices)
            ids = [0]*size
            object.data.vertices.foreach_get('index',ids)

            ranged_val = (dist - proximity*range_m)/(proximity-proximity*range_m)
            threshold_val = 1 if dist  < proximity else 0

            if ranged_grp and ranged_grp in object.vertex_groups.keys():
                object.vertex_groups[ranged_grp].add(ids, ranged_val, 'REPLACE' )

            if threshold_grp and  threshold_grp  in object.vertex_groups.keys():
                object.vertex_groups[threshold_grp].add(ids, threshold_val, 'REPLACE' )

def set_weights(vert,ranged_id,threshold_id,ranged_val,threshold_val):
    
    for group in vert.groups:
        if group.group == ranged_id:
            group.weight = ranged_val

        elif group.group == threshold_id:
            group.weight = threshold_val

def vert_tension(grp,obj,obj_eval,ranged_id,threshold_id):
    filter_verts = grp.vertex_group_filter
    bias = grp.bias * 0.1

    if filter_verts:
        filter_id = obj.vertex_groups[filter_verts].index

    tension_distance = grp.tension_distance

    distances = collections.defaultdict(list)
    weights = collections.defaultdict(float)

    for edge in obj.data.edges:
        id_a = edge.vertices[0]
        id_b = edge.vertices[1]

        included = True

        if filter_verts:
            included = False
            o_vert = obj.data.vertices[id_a]
            for g in o_vert.groups:
                if g.group == filter_id and g.weight >  0.01:
                    included = True
                    break
        if not included:
            continue

        
        #original Verts 
        vert_a = obj.data.vertices[id_a]
        coA =  vert_a.co

        
        vert_b = obj.data.vertices[id_b]
        coB =  vert_b.co
        
        #deformed Verts 
        eval_vert_a = obj_eval.verts[id_a]
        eval_co_a = eval_vert_a.co

        eval_vert_b = obj_eval.verts[id_b]
        eval_co_b = eval_vert_b.co

        #distances

        original_dist = distance_vec(coA,coB)

        new_dist =  distance_vec(eval_co_a,eval_co_b)

        dist = round(new_dist -original_dist,4)
        neighbour_a = (id_a,dist)

        neighbour_b = (id_b,dist)

        distances[id_a].append(neighbour_b)
        distances[id_b].append(neighbour_a)

    #print(distances)  
    

    for id in distances:

        vert= obj.data.vertices[id]

        n = distances.get(id)
        d = [x[1] for x in n]
        #print(d)

        #smallest and largest
        s,l = (min(d),max(d))

        distance_inv = tension_distance * -1 
        if grp.dominance == 'Dominant':
            #take the most extreme
            if  abs(s)-bias > abs(l):#s-bias 
                dist = s
            else:
                dist = l
        else:
            #average
            dist = (s-bias +l)/2
      
        ranged_val = max(min((dist - distance_inv) /(tension_distance - distance_inv),1),0)

        weights[id]=ranged_val

        if threshold_id:
            if s < distance_inv or l > tension_distance:
                threshold_val = 1
            else:
                threshold_val = 0
        else:
            threshold_val =0

        if not grp.average or threshold_id:
            if grp.average:
                temp_ranged_id = None
            else:
                temp_ranged_id = ranged_id
                
            set_weights_tension(vert,temp_ranged_id,threshold_id,ranged_val,threshold_val)  

    if grp.average:
        iterations = grp.iterations
        for n in range(iterations):
            last = True if n == iterations-1 else False
            #print(n,last)
            average(obj,weights,distances,ranged_id,last)

    del distances
    del weights

def average(obj,weights,distances,ranged_id,last):
    
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
                    set_weights_tension(vert_a,ranged_id,None,ranged_val,0)  

            else:
                #print(s,l)
                ranged_val = current_weight
                if last:
                    vert_a = obj.data.vertices[id]
                    set_weights_tension(vert_a,ranged_id,None,ranged_val,0)  

def set_weights_tension(vert,ranged_id,threshold_id,ranged_val,threshold_val):
    
    for group in vert.groups:
        if group.group == ranged_id: 
            group.weight = ranged_val
            
        elif group.group == threshold_id:
            group.weight = threshold_val
          
def distance_vec(point1: Vector, point2: Vector) -> float:
    return (point2 - point1).length       

def update_prop(self,coontext):
    execute(self)

class PROXIMITY_PT_panel(bpy.types.Panel):
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
                    if not grp.vertex_group_ranged:
                        col.enabled = False
                    col.prop(grp,'bias')
                    row = col.row()
                    row.prop(grp,'average')
                    row.prop(grp,'iterations')
                    row = col.row()
                    row.prop(grp,'dominance')


                elif grp.mode =='Proximity':
                    layout.prop(grp,'proximity')
                    layout.prop(grp,'range_multiplier')

                elif grp.mode =='Proximity_obj':
                    if grp.collection and grp.collection.objects:
                        obj = grp.collection.objects[0]
                        layout.prop(grp,'proximity')
                        layout.prop(grp,'range_multiplier')
                        layout.prop(grp,'collection')
                        layout.prop(grp,'neighbours')
                    
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

                layout.box()

class PROXIMITY_OT_add_object(bpy.types.Operator):
    bl_idname = "proximity.add_object" 
    bl_label = "Add Object" 
    bl_options = {'UNDO'}

    def execute(self, context): 
        scene = context.scene
        scene.proximity_objects.add()
        return {'FINISHED'}   

class PROXIMITY_OT_delete_object(bpy.types.Operator):
    bl_idname = "proximity.delete_object" 
    bl_label = "Delete Object" 
    bl_options = {'UNDO'}

    index : IntProperty()

    def execute(self, context): 
        scene = context.scene
        scene.proximity_objects.remove(self.index)
        return {'FINISHED'}   

class PROXIMITY_OT_make_vertGroup(bpy.types.Operator):
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
                self.report({'ERROR'},"No object has been assigned")
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
        items=(('Proximity','Proximity Verts','Proximity for verts within a single mesh'),('Proximity_obj','Proximity Objects','Proximity from target object to collection objects'),
        ('Tension','Tension','Compression and stretch of polys within a single mesh')),
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
    expand : BoolProperty(default= True)


classes = [
    PROXIMITY_PT_panel,
    PROXIMITY_OT_add_object,
    PROXIMITY_OT_delete_object,
    PROXIMITY_OT_make_vertGroup,
    Proximity_objects,

    ]

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    bpy.app.handlers.frame_change_post.append(execute)
    bpy.types.Scene.proximity_objects = CollectionProperty(type = Proximity_objects)



def unregister():
    from bpy.utils import unregister_class
    for cls in classes:
        unregister_class(cls)
    
    bpy.app.handlers.frame_change_post.remove(execute)
    del bpy.types.Scene.proximity_objects

