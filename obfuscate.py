import os
import random
import argparse
import networkx as nx

from pathlib import Path
import circuitgraph as cg

import matplotlib.pyplot as plt


def preprocess_file(netlist_file, top_module, num_nodes_to_invert):
    """
    This function does pre-processing on the input design netlist.

    Preprocessing includes:

    1) Removing the CMOS based DFF defnition given in the benchmark and replacing with our own library DFFSR cell.
    2) Randomly sample some internal nodes and replace them with the XOR of thier original self and an input signal.
           This input pin will be used for flipping the original node.
    3) Write the new file to Verilog.
    """

    os.system("rm -rf generated; mkdir -p generated; cp {} generated/orig_copy.v".format(netlist_file))

    # Comment out the 'dff' module, and remove them from the files
    verilog_lines = []
    with open("generated/orig_copy.v", "r") as orig:
        orig_verilog_lines = orig.readlines()

    modified_verilog_lines = []
    flag = False
    for line in orig_verilog_lines:
        if ((flag) or (("module" in line) and ("dff" in line))):
            flag = True
            line = "// " + line

        if ("endmodule" in line):
            flag = False
            
        modified_verilog_lines.append(line)
            
    with open("generated/orig_copy.v", "w") as modified:
        modified.writelines(modified_verilog_lines)

    # Helps in adding the 'reset' port to the DFFSR
    os.system("./utils/preprocess.sh generated/orig_copy.v > generated/orig_replace_ffx.v")

        
    # Randomly sampling internal nodes and adding an XOR gate for them.
    dff_bb = cg.BlackBox("dff", ["reset", "CK", "D"], ["Q"])    
    ck = cg.from_file("generated/orig_replace_ffx.v", blackboxes = [dff_bb])

    primitive_gates = [
        "and",
        "or",
        "xor",
        "not",
        "nand",
        "nor",
        "xnor",
    ]

    original_inputs = ck.filter_type("input")
    original_outputs = ck.outputs()
    original_internal_nodes = [node for node in ck.filter_type(primitive_gates) if not ck.is_output(node)]
    number_of_nodes = len(original_internal_nodes)

    randomly_sampled_nodes = random.sample(list(original_internal_nodes), num_nodes_to_invert)
    
    for node in randomly_sampled_nodes:
        print(node, ck.type(node))

        ck.add(node + "_flipper", "input")
        
        # Construct a duplicate of the current node
        ck.add(node + "_orig", ck.type(node), fanin=ck.fanin(node))

        # Disconnect all parents feeding into this
        ck.disconnect(ck.fanin(node), node)
        # ck.set_type(node, "buf")

        # Add an 'XOR' gate
        fanouts_of_node = ck.fanout(node)
        ck.remove(node)
        ck.add(node + "_flipped", "xor", fanin={node + "_orig", node + "_flipper"}, fanout = fanouts_of_node)


    # Connect the reset signal
    ck.add("reset", node_type="input", fanout = ["DFF_RESET"])

    cg.to_file(ck, "generated/orig_ffx_2_dffsr.v")
    
    return randomly_sampled_nodes, original_inputs, original_outputs


def construct_obfuscation_graph(key_length, ip_width):
    """
    Constructs a simple NetworkX graph. Steps taken in building the graph are as follows

    1) A random key is generated based on the requested key_length.
    2) The core graph leading to authentication is made based on the generated key.
    3) Additonal states are added all of which finally lead the user back to circuit init state.
    4) All node and edge information are embedded inside it.
    """

    Graph = nx.DiGraph()
    key = dict()
    wrong_transitions = dict()
    additional_non_key_nodes = []

    # Node color is a list maintained which will help in printing the final obfuscation FSM state
    # transitions.
    node_color = []
    
    # Construct the obfuscation FSM
    with open("generated/key.txt", "w") as f:
        for i in range(key_length):
            key_item = random.randint(1, ip_width)
            Graph.add_edge(i, i+1, object=key_item)
            node_color.append("#4CD4EF")
            key[(i, i+1)] = key_item
            f.write(str(key_item)+"\n")

    Graph.add_edge(i+1, i+1, object='default')
    key[(i+1, i+1)] = 'default'
    
    first_state = 0
    # The actual last state is 'valid' initialization state
    # Thus, we must loop only in the states before that.
    last_state  = key_length - 1

    # Add some additional FSM states to make the
    # adversary stay in the obfuscated FSM
    node_idx = key_length + 1
    Graph.add_edge(last_state, node_idx, object='default')
    wrong_transitions[(last_state, node_idx)] = 'default'
    additional_non_key_nodes.append(node_idx)
    node_color.append("#EE8787")

    for i in range(random.randint(int(key_length/2), key_length)):
        Graph.add_edge(node_idx, node_idx+1, object='default')
        node_color.append("#EE8787")
        wrong_transitions[(node_idx, node_idx+1)] = 'default'
        node_idx += 1
        additional_non_key_nodes.append(node_idx)

    # Final transition back to node 0
    Graph.add_edge(node_idx, 0, object='default')
    wrong_transitions[(node_idx, 0)] = 'default'
    node_color.append("#EE8787")


    # Random edges from each node back to
    # No need for a random transition for last obfuscated state
    # node.
    for i in range(key_length-1):
        randomly_picked_node = random.choice(additional_non_key_nodes)
        Graph.add_edge(i, randomly_picked_node, object = 'default')
        wrong_transitions[(i, randomly_picked_node)] = 'default'

    # Visualize the generated obfuscation FSMs
    pos = nx.circular_layout(Graph)    
    nx.draw(Graph, pos, with_labels=True)

    edge_labels = dict()
    for k in key:
        edge_labels[k] = key[k]

    for k in wrong_transitions:
        edge_labels[k] = wrong_transitions[k]

    node_color[key_length] = "#4CEF57"
    
    nx.draw(Graph, pos, node_color = node_color)
    nx.draw_networkx_edge_labels(Graph, pos, edge_labels = edge_labels)
    plt.savefig("generated/obfuscation-fsm.png")            

    return Graph


def _get_verilog_from_transitions(obfuscation_graph, key_length, ip_width, num_nodes_to_invert):
    """
    This is a helper function to the bigger function which spits out the Verilog code by taking in
    a NetworkX graph.
    """

    toret  = ""
    # Get the adjacency list from the obfuscation graph.
    adjacency = dict(obfuscation_graph.adjacency())

    # We need to generate verilog for each of the adjacent transitions shown in the diagram.
    for node_idx in adjacency:
        toret += "\n".join([
            "             {}: begin".format(node_idx),
            "                case (ip_vec)\n",
            ])

        for dest in adjacency[node_idx]:
            # Generate a random number for the inverting vector which will spit out quite a
            # an amount of light.
            op_vec_val = random.randint(2**(num_nodes_to_invert-1), 2**num_nodes_to_invert-1)
            reset_orig_fsm = 0;
            if (dest == node_idx):
                # If there is a self loop which indicates that the current state is 'functional'
                # then make the inverting vector as '0' and initiate resetting the functional FSM.
                op_vec_val = 0;
                reset_orig_fsm = 1;

                # Remain in the functional state as authentication is over. Also, toggle the
                # functional circuit reset signal and let the circuit run.
                toret += "\n".join([
                    "                  {}: begin".format(adjacency[node_idx][dest]['object']),
                    "                     state <= {};".format(dest),
                    "                     if (!reset_flag)",
                    "                       begin",
                    "                          reset_orig_fsm <= 1;",
                    "                          reset_flag <= 1;",
                    "                       end",
                    "                     else",
                    "                       begin",
                    "                          reset_orig_fsm <= 0;",
                    "                       end",
                    "                     op_vec <= {};".format(op_vec_val),
                    "                  end\n",
                ])

            else:
                # If the state is not the functonal state, then append the content to move to the next
                # state based on what the obfuscation FSM graph specifies.
                toret += "\n".join([
                    "                  {}: begin".format(adjacency[node_idx][dest]['object']),
                    "                     state <= {};".format(dest),
                    "                     reset_orig_fsm <= 0;",
                    "                     op_vec <= {};".format(op_vec_val),
                    "                  end\n",
                ])

        toret += "\n".join([
            "                endcase",
            "             end\n",
            ])

    # Just return the string, as it will be appended to prologue, and epilogue of the obfuscation FSM
    # before writing it to a verilog file.
    return toret


def construct_obfuscation_fsm(obfuscation_graph, key_length, ip_width, num_nodes_to_invert):
    """
    This function generates the verilog file by taking the obfuscation FSM graph passed to it.
    """
    # Module header string. This defines the IO ports and also declares some internal variables used
    # by the FSM such as 'state' and 'reset_flag'.
    module_header = "\n".join(["module obfuscation_fsm (",
                               "            input wire          clk,",
                               "            input wire          reset,",
                               "            input wire [{}-1:0]  ip_vec,".format(ip_width),
                               "            output reg  [{}-1:0] op_vec,".format(num_nodes_to_invert),
                               # Reset signal going to the functional part of the circuit.
                               "            output reg          reset_orig_fsm",
                               "            );",
                               "",
                               "   reg [{}:0]                    state;".format((key_length-1).bit_length()),
                               "   reg                             reset_flag;",
                               "",
                               "",
                               ])


    # The module body. The body is expanded mostly by another helper function, but the prologue, and epilogue
    # for the case statement implementing the FSM is as shown below.
    module_body = "\n".join(["   always @(posedge clk)",
                             "     begin",
                             "       if (reset)",
                             "         begin",
                             "           state <= 0;",
                             "           reset_orig_fsm <= 0;",
                             "           reset_flag <= 0;",
                             "           op_vec <= {};".format(random.randint(2**(num_nodes_to_invert-1), 2**num_nodes_to_invert-1)),
                             "         end",
                             "       else",
                             "         begin",
                             "           case(state)",

                             # Call to the helper function which generates the body of the case statement.
                             _get_verilog_from_transitions(obfuscation_graph, key_length, ip_width, num_nodes_to_invert),

                             "           endcase",
                             "         end",
                             "     end"
                             "",
                             "\n"
                            ])

    
    module_footer = "endmodule\n"
    module = module_header + module_body + module_footer

    # The generated verilog is written into a verilog file for further processing by
    # other tools.
    with open("generated/obfuscation_fsm.v", "w") as f:
        f.write(module)

    # TODO: remove this.
    # Also return the verilog string.
    return module
    
def merge(top_module, randomly_sampled_nodes, original_inputs, original_outputs):
    """
    This function generates a verilog file for the top_module which instantiates the original
    design (slightly modified to take in inverting vector) and the obfuscation FSM, and connects
    them together.

    The top_module will have the same IO ports as the original design.
    """
    module_header  = "module top_module (\n           "
    module_header += ",\n           ".join(original_inputs) + ",\n           "
    module_header += ",\n           ".join(original_outputs) + ",\n           "
    module_header += "reset);\n\n"


    module_body     = "   " + ";\n   ".join(["input {}".format(original_input) for original_input in original_inputs]) + ";\n"
    module_body    += "   input reset;\n"
    module_body    += "   " + ";\n   ".join(["output {}".format(original_output) for original_output in original_outputs]) + ";\n"
    module_body    += "   " + ";\n   ".join(["wire reset_orig_fsm", "wire [{}-1:0] op_vec".format(len(randomly_sampled_nodes))]) + ";\n"
    
    
    module_body    += "\n".join([
        "",
        "",
        # Instantiating the obfuscation FSM
        "   obfuscation_fsm obfuscation_fsm_inst(",
        "                                        .clk(CK),",
        "                                        .reset(reset),",
        "                                        .ip_vec({" + ",".join([ip for ip in sorted(original_inputs) if ip != "CK"]) + "}),",
        "                                        .op_vec(op_vec),",
        "                                        .reset_orig_fsm(reset_orig_fsm));",
        "",
        "",
        # Instantiating the original design. 'top_module' contains the module name of the original design.
        "   {0} {0}_inst (".format(top_module),
        "         " + ",\n         ".join([".{0}({0})".format(original_input) for original_input in sorted(original_inputs)]) + ",",
        "         .reset(reset_orig_fsm),",
        # All the "_flipper" inputs for orignal design come from the 'op_vec' outputs from the obfuscation FSM.
        "         " + ",\n         ".join([".{}_flipper(op_vec[{}])".format(sample_node, i) for i,sample_node in enumerate(randomly_sampled_nodes)]) + ",",

        "         " + ",\n         ".join([".{0}({0})".format(original_output) for original_output in original_outputs]) + ");",
        "",
        "",
    ])
    
    module_footer = "endmodule\n"

    module = module_header + module_body + module_footer

    # The generated verilog is written into a verilog file for further processing by
    # other tools.
    with open("generated/top_module.v", "w") as f:
        f.write(module)

    # TODO: remove this
    # Also return the verilog string.
    return module

    
def synthesize_design():
    """
    Call the postprocess script. This script uses Yosys, and CircuitGraph tools
    for synthesizing the design. The Yosys tool generates verilog with expresions such as
    "|, &, ^" etc. As the gate library is not supplied. A final parse of this file through
    CircuitGraph allows us to map these expressions to inbuilt Verilog primitive cells such as 'or',
    'and', and 'xor'.

    This is solely because, Yosys does not support synthesizing using inbuilt Verilog primitive gates.
    """
    os.system("./utils/postprocess.sh")


def main(args):
    """
    This function performs the obfuscation in three steps -

    1) Pre-process the input netlist.
    2) Construct a graph of the obfuscation FSM.
    3) Generate verilog code for the obfuscation FSM.
    4) Merge the generated obfuscation FSM, and the preprocessed input netlist.
    5) Synthesize the design to get the final obfuscated netlist.
    """

    # randombly_sampled_nodes: Nodes from the original circuit which were
    #                          randomly sampled to be inverted by the inverting vector.
    #
    # original_inputs and original_outputs: IO port signals of the original unobfuscated design
    #                                       required while merging designs.
    randomly_sampled_nodes, original_inputs, original_outputs = preprocess_file(str(args.netlist_file), args.top_module, int(args.num_nodes_to_invert))

    # Construct obfuscation FSM's graph. This will help in generating the Verilog code for it.
    obfuscation_graph   = construct_obfuscation_graph(args.key_length, len(original_inputs)-1)

    # Pass the obfuscation graph along with other information to generate the Verilog for the obfuscation FSM.
    obfuscation_fsm_str = construct_obfuscation_fsm(obfuscation_graph, args.key_length, len(original_inputs)-1, len(randomly_sampled_nodes))

    # Construct the top_level Verilog module which instantiates both the unobfuscated design as well as the obfuscation FSM,
    # and connects both of them together. This is the final obfuscated design that needs to be synthesized.
    merge(args.top_module, randomly_sampled_nodes, original_inputs, original_outputs)

    # Finally, synthesize the design to get the gate-level netlist of the obfuscated design.
    synthesize_design()
    

if (__name__ == "__main__"):
    
    parser = argparse.ArgumentParser(description = "Command line arguments for the HARPOON obfuscation tool.")

    parser.add_argument("-f", "--netlist_file",
                        required = True,
                        type = Path,
                        help = "Path of the input netlist file.")

    parser.add_argument("-t", "--top_module",
                        required = True,
                        type = str,
                        help = "Name of the top module.")

    parser.add_argument("-k", "--key_length",
                        default = 5,
                        type = int,
                        help = "Length of the authentication key required.")

    parser.add_argument("-i", "--num_nodes_to_invert",
                        default = 5,
                        type = int,
                        help = "Number of nodes in the original circuit which needs to be inverted.")

    args = parser.parse_args()

    main(args)
