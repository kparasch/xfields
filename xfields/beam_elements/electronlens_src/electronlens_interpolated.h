#ifndef XFIELDS_ELECTRONLENSINTERPOLATED_H
#define XFIELDS_ELECTRONLENSINTERPOLATED_H

/*gpufun*/
void ElectronLensInterpolated_track_local_particle(ElectronLensInterpolatedData el, LocalParticle* part0){

    const double length = ElectronLensInterpolatedData_get_length(el);
    const double current = ElectronLensInterpolatedData_get_current(el);
    const double voltage = ElectronLensInterpolatedData_get_voltage(el);
    TriLinearInterpolatedFieldMapData fmap = ElectronLensInterpolatedData_getp_fieldmap(el);
    /*gpuglmem*/ double* dphi_dx_map = ElectronLensInterpolatedData_getp1_fieldmap_dphi_dx(el, 0);
    /*gpuglmem*/ double* dphi_dy_map = ElectronLensInterpolatedData_getp1_fieldmap_dphi_dy(el, 0);

    // # Electron properties
    // total electron energy
    const double EMASS  = 510998.928;
    const double etot_e       = voltage + EMASS;
    // // electron momentum
    const double p_e          = sqrt(etot_e*etot_e - EMASS*EMASS);
    // // relativistic beta of electron
    const double beta_e       = -p_e/etot_e;

    //start_per_particle_block (part0->part)


        const double x = LocalParticle_get_x(part);
        const double y = LocalParticle_get_y(part);

        // double dphi_dx=0;
        // double dphi_dy=0;
        // double dphi_dtau=0;
        //
        // if( TriCubicInterpolatedFieldMap_interpolate_grad(fmap, 
        //     x, y, 0.,
        //     &dphi_dx, &dphi_dy, &dphi_dtau)
        //   ){
        //       LocalParticle_set_state(part, -11); // Stop tracking particle if it escapes the interpolation grid.
        //   }

	    const IndicesAndWeights iw = 
	        TriLinearInterpolatedFieldMap_compute_indeces_and_weights(fmap, x, y, 0.);

      	const double dphi_dx = 
	        TriLinearInterpolatedFieldMap_interpolate_3d_map_scalar(dphi_dx_map, iw);
      	const double dphi_dy = 
	        TriLinearInterpolatedFieldMap_interpolate_3d_map_scalar(dphi_dy_map, iw);

	    const double q0 = LocalParticle_get_q0(part);
	    const double mass0 = LocalParticle_get_mass0(part);
	    const double chi = LocalParticle_get_chi(part);
	    const double beta0 = LocalParticle_get_beta0(part);
	    const double gamma0 = LocalParticle_get_gamma0(part);
        //const double charge_mass_ratio = 
		//             chi*QELEM*q0/(mass0*QELEM/(C_LIGHT*C_LIGHT));

        // sign corresponds to a counter-rotating electron beam!
        const double factor = -(current*length*QELEM*q0)
                               /(mass0*QELEM*beta0*gamma0*C_LIGHT)
                               *(1.-beta0*beta_e)/beta_e;

	LocalParticle_add_to_px(part, factor*dphi_dx);
	LocalParticle_add_to_py(part, factor*dphi_dy);
    //end_per_particle_block
}

#endif